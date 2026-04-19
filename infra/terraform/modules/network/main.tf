# Network foundation: VPC, three subnet tiers (public / private /
# data) across N AZs, NAT GW, S3 + interface endpoints, and security
# groups for every tier (ALB, STC service, LD relay, data layer).
#
# Uses for_each over the AZ list so subnet additions come from a var
# change, not copy-paste. Data-tier subnets are isolated — no NAT — so
# RDS + ElastiCache can only be reached inside the VPC.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  public_cidrs = [
    for idx, az in local.azs :
    cidrsubnet(var.cidr_block, 4, idx)
  ]
  private_cidrs = [
    for idx, az in local.azs :
    cidrsubnet(var.cidr_block, 4, idx + 4)
  ]
  data_cidrs = [
    for idx, az in local.azs :
    cidrsubnet(var.cidr_block, 4, idx + 8)
  ]
}

resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = "${var.name_prefix}-vpc" }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-igw" }
}

resource "aws_subnet" "public" {
  for_each                = { for idx, az in local.azs : az => local.public_cidrs[idx] }
  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.name_prefix}-public-${each.key}", tier = "public" }
}

resource "aws_subnet" "private" {
  for_each          = { for idx, az in local.azs : az => local.private_cidrs[idx] }
  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = { Name = "${var.name_prefix}-private-${each.key}", tier = "private" }
}

resource "aws_subnet" "data" {
  for_each          = { for idx, az in local.azs : az => local.data_cidrs[idx] }
  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = each.value
  tags              = { Name = "${var.name_prefix}-data-${each.key}", tier = "data" }
}

resource "aws_eip" "nat" {
  for_each = var.per_az_nat ? toset(local.azs) : toset([local.azs[0]])
  domain   = "vpc"
  tags     = { Name = "${var.name_prefix}-eip-${each.key}" }
}

resource "aws_nat_gateway" "this" {
  for_each      = var.per_az_nat ? toset(local.azs) : toset([local.azs[0]])
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id
  tags          = { Name = "${var.name_prefix}-nat-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
  tags = { Name = "${var.name_prefix}-rt-public" }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  for_each = aws_subnet.private
  vpc_id   = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = var.per_az_nat ? aws_nat_gateway.this[each.key].id : aws_nat_gateway.this[local.azs[0]].id
  }
  tags = { Name = "${var.name_prefix}-rt-private-${each.key}" }
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}

resource "aws_route_table" "data" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name_prefix}-rt-data" }
}

resource "aws_route_table_association" "data" {
  for_each       = aws_subnet.data
  subnet_id      = each.value.id
  route_table_id = aws_route_table.data.id
}

# --- Security groups ---------------------------------------------------

resource "aws_security_group" "alb" {
  name_prefix = "${var.name_prefix}-alb-"
  description = "Internal ALB facing API Gateway VPC Link."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "From VPC Link + VPC internal"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    cidr_blocks     = [var.cidr_block]
  }

  ingress {
    description = "HTTP plaintext (ALB -> service)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.cidr_block]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-alb" }
}

resource "aws_security_group" "service" {
  name_prefix = "${var.name_prefix}-svc-"
  description = "STC framework ECS tasks."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "From internal ALB on Flask port"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "From ALB on Prometheus port (scraping)"
    from_port       = 9090
    to_port         = 9090
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All egress (reaches data tier + external APIs via NAT)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-svc" }
}

resource "aws_security_group" "relay" {
  name_prefix = "${var.name_prefix}-relay-"
  description = "LaunchDarkly Relay Proxy."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "From STC service on relay port"
    from_port       = 8030
    to_port         = 8030
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  egress {
    description = "Egress to LD SaaS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-relay" }
}

resource "aws_security_group" "data" {
  name_prefix = "${var.name_prefix}-data-"
  description = "RDS, ElastiCache, Qdrant data layer."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "Postgres from service"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  ingress {
    description     = "Redis from service"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  ingress {
    description     = "Qdrant REST from service"
    from_port       = 6333
    to_port         = 6333
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }

  egress {
    description = "All egress within VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.cidr_block]
  }

  tags = { Name = "${var.name_prefix}-data" }
}

# --- VPC endpoints (S3 gateway + interface endpoints for AWS APIs) ----

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(
    [for rt in aws_route_table.private : rt.id],
    [aws_route_table.data.id],
  )
  tags = { Name = "${var.name_prefix}-vpce-s3" }
}

resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.name_prefix}-vpce-"
  description = "Allows interface VPC endpoints from private subnets."
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "HTTPS from service + relay"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [
      aws_security_group.service.id,
      aws_security_group.relay.id,
    ]
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.name_prefix}-vpce" }
}

locals {
  interface_endpoint_services = toset([
    "ecr.api",
    "ecr.dkr",
    "secretsmanager",
    "logs",
    "sts",
    "ssm",
  ])
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoint_services
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for s in aws_subnet.private : s.id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  tags                = { Name = "${var.name_prefix}-vpce-${each.key}" }
}
