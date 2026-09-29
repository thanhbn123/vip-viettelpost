from app.core.config import settings

class ViettelPostAuth:
    async def get_token(self) -> str:
        # TODO: Implement from the official Viettel Post Partner API auth contract.
        # Never log username/password/token.
        if settings.vtp_token:
            return settings.vtp_token
        raise NotImplementedError(
            "Viettel Post auth chưa được bật. Cần đối chiếu endpoint/payload chính thức và cấp credential test."
        )
