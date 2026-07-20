from app.core.errors import ProviderUnavailable


def test_provider_error_has_stable_public_shape():
    error = ProviderUnavailable("MAAS_UNAVAILABLE", "模型暂时不可用")

    assert error.status_code == 502
    assert error.retryable is True
    assert error.to_dict() == {
        "code": "MAAS_UNAVAILABLE",
        "message": "模型暂时不可用",
        "retryable": True,
    }
