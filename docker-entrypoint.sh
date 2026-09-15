#!/bin/sh
set -e

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

if [ -z "$DB_PATH" ]; then
  export DB_PATH="$DATA_DIR/wallabot.db"
fi

SECRET_KEY_FILE="$DATA_DIR/.secret_key"
if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "changeme" ]; then
  if [ -f "$SECRET_KEY_FILE" ]; then
    export SECRET_KEY="$(cat "$SECRET_KEY_FILE")"
  else
    export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    echo "$SECRET_KEY" > "$SECRET_KEY_FILE"
  fi
fi

python -c "from wallabot import db; db.init_db()"

if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
  python - <<'PYEOF'
import os

from wallabot import users
from wallabot.users import UsernameTakenError

try:
    user = users.create_user(
        username=os.environ["ADMIN_USERNAME"],
        password=os.environ["ADMIN_PASSWORD"],
        email=os.environ.get("ADMIN_EMAIL"),
        is_admin=True,
    )
    print(f"Usuario admin '{user.username}' creado.")
except UsernameTakenError:
    pass
PYEOF
fi

exec "$@"
