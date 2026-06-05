from tidal_tui.services.tidal_service import TidalService
svc = TidalService()
svc.authenticate()
try:
    print("Playlists:", svc.get_playlists())
except Exception as e:
    import traceback
    traceback.print_exc()
