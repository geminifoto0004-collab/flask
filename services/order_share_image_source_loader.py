"""Late-load source-level share image visibility after all share/cache patches."""
from blueprints.b2_test_bp import b2_test_bp

@b2_test_bp.record_once
def _late_install_order_share_image_source(state):
    # Imported during blueprint registration, after services.__init__ has loaded the
    # existing visibility/cache layers.  This ensures the source-level patch is the
    # final owner of share image filtering without changing import order elsewhere.
    from services import order_share_image_source_patch  # noqa: F401
