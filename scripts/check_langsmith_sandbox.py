"""Opt-in remote smoke test: synthetic arithmetic only; no sports data uploads.

Run from the repository root after configuring your own LangSmith credentials.
Creating a sandbox consumes the account's sandbox allowance or billable usage.
"""
from sports_analyst.config import Settings


def main():
    from langsmith.sandbox import SandboxClient

    settings = Settings()
    if not settings.langsmith_api_key:
        raise SystemExit("Configure LANGSMITH_API_KEY privately in .env first")
    headers = {"X-Tenant-Id": settings.langsmith_workspace_id} if settings.langsmith_workspace_id else None
    client = SandboxClient(api_key=settings.langsmith_api_key.get_secret_value(),
                           api_endpoint=settings.langsmith_endpoint, headers=headers)
    with client.sandbox(idle_ttl_seconds=60, timeout=30) as sandbox:
        result = sandbox.run('python3 -c "print(2 + 2)"', timeout=10)
        if not result.success or result.stdout.strip() != "4":
            raise SystemExit("Sandbox arithmetic smoke test failed; inspect the sandbox in LangSmith")
        print("Sandbox arithmetic succeeded. The temporary sandbox will now be deleted.")


if __name__ == "__main__":
    main()
