# SSH_ASKPASS для команд темы Remarkable: печатает пароль активного
# пресета RCU, чтобы ssh не спрашивал его руками. Запускает его только
# ssh через askpass.cmd; вручную запускать незачем, он выведет пароль.
. (Join-Path $PSScriptRoot '..\..\Private\Remarkable\RemarkablePreset.ps1')
[Console]::Out.Write((Get-ActiveRemarkablePreset).password)
