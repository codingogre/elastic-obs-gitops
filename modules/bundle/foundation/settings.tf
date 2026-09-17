# Kibana global settings the bundle depends on. Only environments that own their project manage them
# (settings.manage_global_settings): the shared dev project's global settings are not ours.
resource "elasticgitops_kibana_setting" "alerting_v2" {
  count = var.settings.manage_global_settings && var.settings.alerting_v2_enabled ? 1 : 0

  scope = "global"
  key   = "alerting:v2:enabled"
  value = jsonencode(true)
}
