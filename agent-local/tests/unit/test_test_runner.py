from agent_local.test_runner import _COVERAGE_TOTAL, _DIFF_STAT_SUMMARY, detect_affected_services


def test_detect_affected_services_um_servico() -> None:
    files = ["transaction-service/app/services/transaction_service.py", "specs/business/16-x.md"]
    assert detect_affected_services(files) == ["transaction-service"]


def test_detect_affected_services_multiplos_servicos() -> None:
    files = ["account-service/app/models/account.py", "transaction-service/app/models/transaction.py"]
    assert detect_affected_services(files) == ["account-service", "transaction-service"]


def test_detect_affected_services_nenhum() -> None:
    assert detect_affected_services(["docs/escopo-arquitetura.md", "README.md"]) == []


def test_diff_stat_summary_regex_extrai_insercoes_e_delecoes() -> None:
    texto = " 3 files changed, 42 insertions(+), 7 deletions(-)"
    match = _DIFF_STAT_SUMMARY.search(texto)
    assert match is not None
    assert match.group(2) == "42"
    assert match.group(3) == "7"


def test_diff_stat_summary_regex_so_insercoes() -> None:
    texto = " 1 file changed, 5 insertions(+)"
    match = _DIFF_STAT_SUMMARY.search(texto)
    assert match is not None
    assert match.group(2) == "5"
    assert match.group(3) is None


def test_coverage_total_regex_extrai_percentual() -> None:
    texto = "app/services/x.py    50    5    90%\nTOTAL                120    15    88%"
    match = _COVERAGE_TOTAL.search(texto)
    assert match is not None
    assert match.group(1) == "88"
