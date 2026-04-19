variable "name_prefix" {
  type = string
}

variable "purposes" {
  description = "Map of purpose key -> human-readable description."
  type        = map(string)
}
