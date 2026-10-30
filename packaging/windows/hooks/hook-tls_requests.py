"""Keep the source file whose physical path the TLS loader resolves strictly."""

# Import still uses PYZ bytecode; the companion .py makes resolve(strict=True)
# succeed and retains the package-relative bin/ lookup in the frozen runtime.
module_collection_mode = {"tls_requests.models.libraries": "pyz+py"}
