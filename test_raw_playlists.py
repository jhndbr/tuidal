from tidal_tui.services.tidal_service import TidalService
import json
svc = TidalService()
svc.authenticate()
try:
    resp = svc._session.request.request("GET", f"users/{svc._session.user.id}/playlists").json()
    print("Raw playlists keys:", resp.keys() if isinstance(resp, dict) else "Not dict")
    if isinstance(resp, dict) and "items" in resp:
        for item in resp["items"][:2]:
            print(json.dumps(item, indent=2))
except Exception as e:
    import traceback
    traceback.print_exc()
