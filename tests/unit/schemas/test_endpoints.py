import pytest

from f1.exceptions import ConfigurationError
from f1.schemas.endpoints import ENDPOINTS, Partition, Scope, endpoints_by_scope, get_endpoints
from f1.schemas.silver import CONTRACTS


def test_registro_cobre_os_18_endpoints() -> None:
    assert len(ENDPOINTS) == 18
    assert {spec.name for spec in endpoints_by_scope(Scope.YEAR)} == {"meetings", "sessions"}
    assert {spec.name for spec in endpoints_by_scope(Scope.SESSION_DRIVER)} == {
        "car_data",
        "location",
    }
    assert {name for name, spec in ENDPOINTS.items() if spec.race_only} == {
        "intervals",
        "overtakes",
        "championship_drivers",
        "championship_teams",
    }


def test_drivers_vem_antes_da_telemetria() -> None:
    names = [spec.name for spec in endpoints_by_scope(Scope.SESSION, Scope.SESSION_DRIVER)]

    assert names.index("drivers") < names.index("car_data")


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_contrato_contem_chave_primaria_e_descarta_deprecados(name: str) -> None:
    spec, contract = ENDPOINTS[name], CONTRACTS[name]

    assert set(spec.primary_key) <= contract.silver.keys()
    assert not set(spec.deprecated_fields) & contract.silver.keys()
    assert set(spec.deprecated_fields) <= contract.optional


def test_get_endpoints_valida_nomes() -> None:
    assert [spec.name for spec in get_endpoints("stints, laps")] == ["laps", "stints"]

    with pytest.raises(ConfigurationError, match="lapz"):
        get_endpoints("laps,lapz")
    with pytest.raises(ConfigurationError):
        get_endpoints(" , ")


@pytest.mark.parametrize(
    ("partition", "path"),
    [
        (Partition(2023), "year=2023"),
        (Partition(2023, 9165), "year=2023/session_key=9165"),
        (Partition(2023, 9165, 1), "year=2023/session_key=9165/driver_number=1"),
    ],
)
def test_partition_ida_e_volta_pelo_caminho(partition: Partition, path: str) -> None:
    assert partition.path == path
    assert Partition.from_path(path) == partition


@pytest.mark.parametrize("path", ["session_key=1", "year=abc", "lixo"])
def test_partition_caminho_invalido(path: str) -> None:
    with pytest.raises(ConfigurationError):
        Partition.from_path(path)
