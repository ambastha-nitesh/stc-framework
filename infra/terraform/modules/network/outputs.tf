output "vpc_id" { value = aws_vpc.this.id }
output "vpc_cidr" { value = aws_vpc.this.cidr_block }

output "public_subnet_ids" {
  value = [for s in aws_subnet.public : s.id]
}

output "private_subnet_ids" {
  value = [for s in aws_subnet.private : s.id]
}

output "data_subnet_ids" {
  value = [for s in aws_subnet.data : s.id]
}

output "security_group_ids" {
  value = {
    alb     = aws_security_group.alb.id
    service = aws_security_group.service.id
    relay   = aws_security_group.relay.id
    data    = aws_security_group.data.id
  }
}

output "availability_zones" { value = local.azs }
