"""
STC Framework - Stalwart: Financial Document Q&A Agent

A LangGraph-based RAG agent that answers questions about financial documents.
The Stalwart executes tasks. It does not judge itself, optimize itself, or
govern itself. Those responsibilities belong to the Trainer and Critic.
"""

import os
import json
import logging
from typing import TypedDict, Annotated, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.documents import Document
from opentelemetry import trace

from spec.loader import load_spec

logger = logging.getLogger("stc.stalwart")
tracer = trace.get_tracer("stc.stalwart")


# ============================================================================
# State Definition
# ============================================================================

class AgentState(TypedDict):
    """State flowing through the LangGraph workflow."""
    query: str
    retrieved_chunks: list[Document]
    retrieval_scores: list[float]
    context: str
    response: str
    citations: list[dict]
    tool_calls: list[dict]
    data_tier: str  # Classification tier of the query
    model_used: str
    spec_version: str
    prompt_version: str
    turn_count: int
    error: Optional[str]


# ============================================================================
# Workflow Nodes
# ============================================================================

class FinancialQAAgent:
    """
    The Stalwart agent for financial document Q&A.
    
    Workflow: classify → retrieve → assemble_context → reason → format_response
    
    The agent does NOT:
    - Evaluate its own accuracy
    - Choose its own guardrails
    - Optimize its own prompts
    - Decide if it's safe to respond
    
    Those are the Trainer's and Critic's jobs.
    """
    
    def __init__(self, spec_path: str = "spec/stc-spec.yaml"):
        self.spec = load_spec(spec_path)
        self._setup_components()
        self._build_graph()
    
    def _setup_components(self):
        """Initialize retriever, LLM client, and tools."""
        from sentinel.gateway import SentinelGateway
        from sentinel.data_classifier import DataClassifier
        
        self.gateway = SentinelGateway(self.spec)
        self.classifier = DataClassifier(self.spec)
        
        # Vector store connection (local, per data sovereignty)
        vs_config = self.spec.data_sovereignty.get("vector_store", {})
        self.vector_store_host = vs_config.get("host", "http://localhost:6333")
        self.collection_name = "financial_docs"
        
        # Load system prompt from prompt registry
        self.system_prompt = self._load_system_prompt()
        self.prompt_version = "v1.0"  # Updated by Trainer via Langfuse
    
    def _load_system_prompt(self) -> str:
        """Load the system prompt. In production, fetched from Langfuse."""
        return """You are a financial document analysis assistant. You answer 
questions about financial documents (SEC filings, earnings reports, fund 
prospectuses) based ONLY on the provided context.

RULES:
1. Only use information from the provided document context
2. Always cite the source document and page/section when stating facts
3. If the context doesn't contain the answer, say so explicitly
4. Never provide investment advice, buy/sell recommendations, or portfolio suggestions
5. When citing numbers, use the exact figures from the source documents
6. If asked to compare periods, clearly label which period each number belongs to
7. For calculations, show your work step by step

FORMAT:
- Lead with a direct answer
- Support with specific citations: [Source: document_name, page X]
- If computation is needed, show the calculation"""

    def _build_graph(self):
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("classify", self.classify_query)
        workflow.add_node("retrieve", self.retrieve_documents)
        workflow.add_node("assemble_context", self.assemble_context)
        workflow.add_node("reason", self.reason_and_answer)
        workflow.add_node("format_response", self.format_response)
        
        # Define edges
        workflow.set_entry_point("classify")
        workflow.add_edge("classify", "retrieve")
        workflow.add_edge("retrieve", "assemble_context")
        workflow.add_edge("assemble_context", "reason")
        workflow.add_edge("reason", "format_response")
        workflow.add_edge("format_response", END)
        
        self.graph = workflow.compile()
    
    @tracer.start_as_current_span("stalwart.classify")
    def classify_query(self, state: AgentState) -> AgentState:
        """Classify the data sensitivity tier of the incoming query."""
        data_tier = self.classifier.classify(state["query"])
        
        span = trace.get_current_span()
        span.set_attribute("stc.data_tier", data_tier)
        span.set_attribute("stc.spec_version", self.spec.version)
        
        return {
            **state,
            "data_tier": data_tier,
            "spec_version": self.spec.version,
            "prompt_version": self.prompt_version,
        }
    
    @tracer.start_as_current_span("stalwart.retrieve")
    def retrieve_documents(self, state: AgentState) -> AgentState:
        """Retrieve relevant document chunks from the local vector store."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct
            import numpy as np
            
            client = QdrantClient(url=self.vector_store_host)
            
            # Embed the query locally (data sovereignty: embeddings stay local)
            query_embedding = self._embed_query(state["query"])
            
            # Search the vector store
            results = client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                limit=5,  # Top-k; Trainer may optimize this
            )
            
            chunks = []
            scores = []
            for result in results:
                chunks.append(Document(
                    page_content=result.payload.get("text", ""),
                    metadata={
                        "source": result.payload.get("source", "unknown"),
                        "page": result.payload.get("page", 0),
                        "section": result.payload.get("section", ""),
                        "chunk_id": result.id,
                    }
                ))
                scores.append(result.score)
            
            span = trace.get_current_span()
            span.set_attribute("stc.retrieval.num_chunks", len(chunks))
            span.set_attribute("stc.retrieval.avg_score", float(np.mean(scores)) if scores else 0.0)
            
            return {**state, "retrieved_chunks": chunks, "retrieval_scores": scores}
        
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            return {**state, "retrieved_chunks": [], "retrieval_scores": [], "error": str(e)}
    
    @tracer.start_as_current_span("stalwart.assemble_context")
    def assemble_context(self, state: AgentState) -> AgentState:
        """Assemble retrieved chunks into a context string for the LLM."""
        if not state["retrieved_chunks"]:
            return {**state, "context": "No relevant documents found."}
        
        context_parts = []
        for i, chunk in enumerate(state["retrieved_chunks"]):
            source = chunk.metadata.get("source", "unknown")
            page = chunk.metadata.get("page", "?")
            section = chunk.metadata.get("section", "")
            
            header = f"[Document: {source}, Page {page}"
            if section:
                header += f", Section: {section}"
            header += "]"
            
            context_parts.append(f"{header}\n{chunk.page_content}")
        
        context = "\n\n---\n\n".join(context_parts)
        
        span = trace.get_current_span()
        span.set_attribute("stc.context.length_chars", len(context))
        span.set_attribute("stc.context.num_sources", len(context_parts))
        
        return {**state, "context": context}
    
    @tracer.start_as_current_span("stalwart.reason")
    def reason_and_answer(self, state: AgentState) -> AgentState:
        """Call the LLM to generate an answer based on context."""
        
        # Route through the Sentinel gateway (handles model selection + data tier)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"""Based on the following financial document context, 
answer the user's question.

CONTEXT:
{state['context']}

QUESTION: {state['query']}

Remember: Only use information from the context above. Cite sources."""}
        ]
        
        try:
            response = self.gateway.completion(
                messages=messages,
                data_tier=state["data_tier"],
                metadata={
                    "stc_persona": "stalwart",
                    "spec_version": state["spec_version"],
                    "prompt_version": state["prompt_version"],
                }
            )
            
            answer = response.choices[0].message.content
            model_used = response.model
            
            span = trace.get_current_span()
            span.set_attribute("stc.model_used", model_used)
            span.set_attribute("stc.response.length_chars", len(answer))
            
            if hasattr(response, "usage"):
                span.set_attribute("stc.tokens.prompt", response.usage.prompt_tokens)
                span.set_attribute("stc.tokens.completion", response.usage.completion_tokens)
            
            return {**state, "response": answer, "model_used": model_used}
        
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {**state, "response": "", "model_used": "error", "error": str(e)}
    
    @tracer.start_as_current_span("stalwart.format_response")
    def format_response(self, state: AgentState) -> AgentState:
        """Extract citations from the response for audit trail."""
        citations = []
        
        # Parse citations from response (looking for [Source: ...] patterns)
        import re
        citation_pattern = r'\[(?:Source|Document):\s*([^\]]+)\]'
        matches = re.findall(citation_pattern, state.get("response", ""))
        
        for match in matches:
            citations.append({
                "reference": match.strip(),
                "timestamp": datetime.utcnow().isoformat(),
            })
        
        span = trace.get_current_span()
        span.set_attribute("stc.citations.count", len(citations))
        
        return {**state, "citations": citations}
    
    def _embed_query(self, query: str) -> list[float]:
        """Embed query using the local embedding model (data sovereignty)."""
        import requests
        
        embed_config = self.spec.data_sovereignty.get("embedding_model", {})
        endpoint = embed_config.get("endpoint", "http://localhost:11434")
        model = embed_config.get("model", "bge-large-en-v1.5")
        
        response = requests.post(
            f"{endpoint}/api/embeddings",
            json={"model": model, "prompt": query}
        )
        response.raise_for_status()
        return response.json()["embedding"]
    
    def run(self, query: str) -> dict:
        """Execute the full Q&A workflow."""
        initial_state: AgentState = {
            "query": query,
            "retrieved_chunks": [],
            "retrieval_scores": [],
            "context": "",
            "response": "",
            "citations": [],
            "tool_calls": [],
            "data_tier": "internal",  # Default; classify node will update
            "model_used": "",
            "spec_version": "",
            "prompt_version": "",
            "turn_count": 0,
            "error": None,
        }
        
        with tracer.start_as_current_span("stalwart.workflow") as span:
            span.set_attribute("stc.query", query[:200])  # Truncate for safety
            span.set_attribute("stc.persona", "stalwart")
            
            result = self.graph.invoke(initial_state)
            
            span.set_attribute("stc.workflow.completed", result.get("error") is None)
        
        return result


# ============================================================================
# Entry Point
# ============================================================================

def create_agent(spec_path: str = "spec/stc-spec.yaml") -> FinancialQAAgent:
    """Factory function to create a configured Stalwart agent."""
    return FinancialQAAgent(spec_path=spec_path)


if __name__ == "__main__":
    agent = create_agent()
    result = agent.run("What was the total revenue for FY2024?")
    print(f"\nAnswer: {result['response']}")
    print(f"Model: {result['model_used']}")
    print(f"Data Tier: {result['data_tier']}")
    print(f"Citations: {result['citations']}")
