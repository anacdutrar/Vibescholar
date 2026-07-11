import bcrypt

def hash_password(password: str) -> str:
    # Encodes the password to bytes
    password_bytes = password.encode('utf-8')
    # Hashes the password with a work factor of 12 (as requested in NFR05)
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False
