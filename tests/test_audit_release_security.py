import base64

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def test_pyjwt_rejects_private_jwk_with_mismatched_public_identity():
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
    legitimate = Ed25519PrivateKey.generate()
    unrelated = Ed25519PrivateKey.generate()
    jwk = {"kty": "OKP", "crv": "Ed25519",
           "x": encode(legitimate.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)),
           "d": encode(unrelated.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))}
    with pytest.raises(jwt.InvalidKeyError):
        jwt.PyJWK.from_dict(jwk)
