"""
STC Framework - Reference Implementation Runner

This is the main entry point for the Financial Document Q&A reference
implementation. It demonstrates the full STC loop:

1. Stalwart receives a query and produces a response
2. Critic evaluates the response before delivery
3. Trainer records the trace and computes optimization signals
4. All activity is traced via OpenTelemetry for audit

Run: python reference-impl/scripts/run_agent.py
"""

import sys
import os
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from spec.loader import load_spec
from stalwart.financial_qa_agent import FinancialQAAgent
from critic.governance_engine import Critic
from trainer.optimization_manager import Trainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("stc.runner")


class STCSystem:
    """
    The complete STC system: Stalwart + Trainer + Critic working together.
    
    Flow:
    1. User query → Stalwart (via Sentinel gateway)
    2. Stalwart response → Critic (governance evaluation)
    3. If Critic passes → response delivered to user
    4. If Critic blocks → response withheld, user notified
    5. Trace → Trainer (optimization signals recorded)
    6. Trainer adjusts routing/prompts based on accumulated signals
    """
    
    def __init__(self, spec_path: str = "spec/stc-spec.yaml"):
        self.spec = load_spec(spec_path)
        
        logger.info(f"Initializing STC System: {self.spec.name} v{self.spec.version}")
        
        # Initialize the three personas
        self.stalwart = FinancialQAAgent(spec_path=spec_path)
        self.critic = Critic(spec_path=spec_path)
        self.trainer = Trainer(spec_path=spec_path)
        
        # Counters for reporting
        self.total_queries = 0
        self.total_passed = 0
        self.total_blocked = 0
        self.total_warnings = 0
    
    def query(self, user_query: str) -> dict:
        """
        Process a user query through the full STC pipeline.
        
        Returns a dict with:
        - response: The answer (if governance passed)
        - governance: The Critic's verdict
        - optimization: The Trainer's signals
        - metadata: Trace IDs, model used, data tier, etc.
        """
        self.total_queries += 1
        trace_id = f"stc-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{self.total_queries:04d}"
        
        logger.info(f"[{trace_id}] Query: {user_query[:100]}...")
        
        # ── Step 1: Stalwart executes ──────────────────────────────────
        stalwart_result = self.stalwart.run(user_query)
        stalwart_result["trace_id"] = trace_id
        
        logger.info(
            f"[{trace_id}] Stalwart: model={stalwart_result.get('model_used')}, "
            f"tier={stalwart_result.get('data_tier')}, "
            f"chunks={len(stalwart_result.get('retrieved_chunks', []))}"
        )
        
        # ── Step 2: Critic evaluates ───────────────────────────────────
        verdict = self.critic.evaluate(stalwart_result)
        
        logger.info(
            f"[{trace_id}] Critic: {'PASS' if verdict.passed else 'FAIL'}, "
            f"action={verdict.action}, "
            f"escalation={verdict.escalation_level or 'none'}"
        )
        
        # ── Step 3: Determine response to user ─────────────────────────
        if verdict.action == "pass":
            user_response = stalwart_result.get("response", "")
            self.total_passed += 1
        elif verdict.action == "warn":
            user_response = (
                stalwart_result.get("response", "") +
                "\n\n⚠️ Note: This response has been flagged for review. "
                "Please verify critical figures against source documents."
            )
            self.total_warnings += 1
        elif verdict.action == "block":
            user_response = (
                "I was unable to generate a verified answer to your question. "
                "The response was blocked by governance checks because: " +
                "; ".join([
                    r.details for r in verdict.results
                    if not r.passed and r.severity == "critical"
                ]) +
                "\n\nPlease rephrase your question or consult the source documents directly."
            )
            self.total_blocked += 1
        elif verdict.action == "escalate":
            level = verdict.escalation_level
            if level == "suspension":
                user_response = (
                    "This system has been suspended due to repeated governance failures. "
                    "Human review is required before the system can resume."
                )
            elif level == "quarantine":
                user_response = (
                    "This response is being held for human review before delivery. "
                    "You will be notified when it has been verified."
                )
            else:  # degraded
                user_response = (
                    stalwart_result.get("response", "") +
                    "\n\n⚠️ DEGRADED MODE: This system is operating with reduced confidence. "
                    "All figures should be independently verified against source documents."
                )
            self.total_blocked += 1
        else:
            user_response = stalwart_result.get("response", "")
        
        # ── Step 4: Trainer records optimization signals ───────────────
        trainer_transition = self.trainer.on_trace_received({
            **stalwart_result,
            "hallucination_detected": not verdict.passed,
            "accuracy": 1.0 if verdict.passed else 0.0,
        })
        
        # Send Critic feedback to Trainer
        if not verdict.passed:
            critic_feedback = self.critic.format_trainer_feedback(verdict)
            logger.info(
                f"[{trace_id}] Critic → Trainer feedback: "
                f"{len(critic_feedback['failures'])} failures"
            )
        
        # ── Assemble result ────────────────────────────────────────────
        return {
            "trace_id": trace_id,
            "response": user_response,
            "governance": {
                "passed": verdict.passed,
                "action": verdict.action,
                "escalation_level": verdict.escalation_level,
                "rail_results": [
                    {
                        "name": r.rail_name,
                        "passed": r.passed,
                        "severity": r.severity,
                        "details": r.details,
                    }
                    for r in verdict.results
                ],
            },
            "optimization": {
                "reward": trainer_transition.get("reward", 0),
                "signals": trainer_transition.get("signals", []),
            },
            "metadata": {
                "model_used": stalwart_result.get("model_used"),
                "data_tier": stalwart_result.get("data_tier"),
                "spec_version": stalwart_result.get("spec_version"),
                "prompt_version": stalwart_result.get("prompt_version"),
                "citations": stalwart_result.get("citations", []),
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
    
    def submit_feedback(self, trace_id: str, feedback: str):
        """Submit explicit user feedback for a previous response."""
        self.trainer.on_user_feedback(trace_id, feedback)
        logger.info(f"[{trace_id}] User feedback recorded: {feedback}")
    
    def health_check(self) -> dict:
        """Run a system health check across all personas."""
        trainer_report = self.trainer.run_health_check()
        
        return {
            "system": self.spec.name,
            "version": self.spec.version,
            "status": trainer_report.get("status", "unknown"),
            "stats": {
                "total_queries": self.total_queries,
                "passed": self.total_passed,
                "blocked": self.total_blocked,
                "warnings": self.total_warnings,
                "pass_rate": self.total_passed / max(self.total_queries, 1),
            },
            "trainer": trainer_report,
            "escalation_level": self.critic.escalation.current_level,
        }


# ============================================================================
# Interactive CLI
# ============================================================================

def run_interactive():
    """Run the STC system in interactive mode."""
    print("=" * 70)
    print("  STC Framework - Financial Document Q&A")
    print("  Stalwart · Trainer · Critic")
    print("=" * 70)
    print()
    
    system = STCSystem()
    
    print("System initialized. Type your questions about financial documents.")
    print("Commands: /health, /feedback <trace_id> <thumbs_up|thumbs_down>, /quit")
    print()
    
    while True:
        try:
            user_input = input("📄 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        if user_input == "/quit":
            break
        
        if user_input == "/health":
            report = system.health_check()
            print(f"\n📊 Health Report:")
            print(f"   Status: {report['status']}")
            print(f"   Queries: {report['stats']['total_queries']}")
            print(f"   Pass Rate: {report['stats']['pass_rate']:.1%}")
            print(f"   Escalation: {report['escalation_level'] or 'None'}")
            print()
            continue
        
        if user_input.startswith("/feedback"):
            parts = user_input.split()
            if len(parts) == 3:
                system.submit_feedback(parts[1], parts[2])
                print("   ✓ Feedback recorded\n")
            else:
                print("   Usage: /feedback <trace_id> <thumbs_up|thumbs_down>\n")
            continue
        
        # Process the query
        result = system.query(user_input)
        
        # Display response
        print(f"\n🤖 Agent [{result['trace_id']}]:")
        print(f"   {result['response'][:500]}")
        
        # Display governance status
        gov = result["governance"]
        gov_icon = "✅" if gov["passed"] else "🚫"
        print(f"\n   {gov_icon} Governance: {gov['action']}")
        for rail in gov["rail_results"]:
            icon = "✓" if rail["passed"] else "✗"
            print(f"      {icon} {rail['name']}: {rail['details']}")
        
        # Display optimization signal
        opt = result["optimization"]
        print(f"   📈 Reward: {opt['reward']:.3f}")
        print()


if __name__ == "__main__":
    run_interactive()
