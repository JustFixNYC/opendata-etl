# SPDX-License-Identifier: AGPL-3.0-only
output "instance_id" {
  value = try(aws_instance.orchestrator[0].id, null)
}

output "private_ip" {
  value = try(aws_instance.orchestrator[0].private_ip, null)
}
