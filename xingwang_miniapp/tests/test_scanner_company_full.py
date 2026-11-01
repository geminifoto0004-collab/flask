"""Scanner company-cookie full query is separately authenticated and read-only."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
def test_endpoint_auth_and_read_only():
 s=(ROOT/"miniapp_server.py").read_text(encoding="utf-8")
 ast.parse(s)
 part=s[s.index('@app.post("/scanner/api/full")'):s.index('@app.websocket("/bridge")')]
 for marker in ('scanner_backend._check_origin(request)','scanner_backend._require(request)',
                '"source":"scanner_full"','"scanner_actor":actor',
                'if action not in ("stock", "nota", "history_more", "nota_details")',
                'hmac.new(scanner_backend._key(),token.encode("utf-8"),hashlib.sha256)'):
  assert marker in part,marker
 assert 'init_data' not in part
def test_frontend_uses_company_login():
 s=(ROOT/"scanner.html").read_text(encoding="utf-8")
 assert "fetch('/scanner/api/full'" in s
 assert "if(!initData)throw" not in s
 assert 'fullAuthNote' not in s
