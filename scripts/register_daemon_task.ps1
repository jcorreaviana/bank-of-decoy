<#
Registra (ou substitui) uma Scheduled Task do Windows para um dos daemons
dos agentes (agent-local, agent-preditivo) - issue #81, decisao registrada
em specs/tech/cold-start.md.

Chamado por scripts/daemon_tasks.py (nunca direto pelo operador). Sem
Trigger - a task existe so para ser disparada sob demanda
(`schtasks /run /tn <nome>`), nunca em um horario agendado.

Por que Scheduled Task nasce sem ancestralidade de sessao Claude Code/VS
Code por design (nao so por disciplina do operador que a inicia): o
processo real do daemon e criado pelo servico Task Scheduler do Windows
(svchost, PID/ambiente proprios), nunca como filho direto de quem chamou
`schtasks /run` - mesmo que esse chamador seja o proprio terminal integrado
de uma sessao Claude Code/VS Code. O ambiente do processo filho vem do
registro (HKCU\Environment do usuario), nao da arvore de processos de quem
disparou o `/run`.
#>
param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Arguments,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"

$action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $WorkingDirectory

# ExecutionTimeLimit = zero (sem teto) - o padrao do Task Scheduler e matar
# a task apos 72h, o que mataria um daemon de polling continuo pensado para
# rodar indefinidamente. RestartCount/RestartInterval reinicia o daemon
# sozinho se ele cair (ex. excecao nao tratada escapando do loop de
# polling), sem depender do operador notar e relancar manualmente.
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# LogonType Interactive + RunLevel Limited: roda com o mesmo perfil do
# usuario atual (credenciais do `gh` CLI, acesso ao Ollama local), sem
# precisar armazenar senha (o que "Run whether user is logged on or not"
# exigiria).
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Scheduled Task '$TaskName' registrada (sem trigger - so roda sob demanda via 'schtasks /run /tn $TaskName')."
