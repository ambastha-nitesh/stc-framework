variable "name_prefix" {
  description = "Prefix applied to every resource Name tag."
  type        = string
}

variable "region" {
  description = "AWS region (used to build VPC endpoint service names)."
  type        = string
}

variable "cidr_block" {
  description = "CIDR block for the VPC."
  type        = string
}

variable "az_count" {
  description = "Number of Availability Zones to cover."
  type        = number
  default     = 2
}

variable "per_az_nat" {
  description = "Create one NAT Gateway per AZ (prod). When false, a single NAT in the first AZ serves all private subnets (dev)."
  type        = bool
  default     = false
}
