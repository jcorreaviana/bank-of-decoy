KNOWN_FAILURE_TYPES = {
    "timeout",
    "503",
    "500",
    "latencia",
    # Fase 2b (issue #52, specs/business/24-camada-caos-avancada.md)
    "kafka_lag",
    "kafka_delay",
    "degradacao_progressiva",
    "payload_corrompido_sutil",
}
