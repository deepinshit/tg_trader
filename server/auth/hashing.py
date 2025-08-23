from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# sensible defaults
_ph = PasswordHasher()

def hash_password(password: str) -> str:
    return _ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False

def needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)
