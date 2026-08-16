variable "app_name"          { type = string  default = "scrapyard-app" }
variable "region"            { type = string  default = "us-east-1" }
variable "replicas"          { type = number  default = 3 }
variable "db_instance_class" { type = string  default = "db.t3.medium" }
variable "redis_node_type"   { type = string  default = "cache.t3.micro" }
