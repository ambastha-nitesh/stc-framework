# Zero-modification wrapper around the official LaunchDarkly Relay
# Proxy image. We rebuild only to land it in our ECR so that ECS tasks
# pulling from a private VPC (via the ECR VPC endpoint) do not need
# Docker Hub connectivity or authenticated pulls.
#
# The upstream image already exposes port 8030 and runs as a minimal
# static Go binary — nothing to change here.
FROM launchdarkly/ld-relay:7
