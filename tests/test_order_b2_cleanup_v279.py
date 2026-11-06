"""V279 B2 destructive endpoint guardrails; no live TiDB or B2 calls."""
import ast
import pathlib
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"services/order_b2_safe_cleanup_v279.py").read_text("utf-8")
TREE=ast.parse(SOURCE)


def pure(name, ns):
    import copy
    fn=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name==name)
    wrapper=ast.Module(body=[copy.deepcopy(fn)],type_ignores=[])
    exec(compile(ast.fix_missing_locations(wrapper),"<v279>", "exec"),ns)
    return ns[name]


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.fn=pure("_eligible_reason",{
            "CANCELLED":{"CANCELADO","CANCELLED"},
            "pending_pickup":lambda order:any(
                str(x.get("status") or "").upper()=="ARRIVED_IQUIQUE" and
                x.get("pickup_status")!="picked_up"
                for x in order.get("logistics",[])),
            "retention_reason":lambda order,asset,active:(
                "candidate_completed_over_three_months" if
                order.get("old") and asset.get("sha256")=="abc"
                else "keep_recent_completion"),
        })
        self.asset={"sha256":"abc","workflow_key":"X"}
        self.ready={"order_status":"ACTIVE","old":True,
                    "workflows":[{"status":"COMPLETED"}],
                    "logistics":[{"status":"ARRIVED_IQUIQUE","pickup_status":"picked_up"}]}

    def test_cancelled_even_if_recent(self):
        order={**self.ready,"order_status":"CANCELADO","old":False}
        self.assertEqual(self.fn(order,self.asset,[{"history_scope":"current"}],True),"cancelled_order")

    def test_pending_pickup_protects_even_cancelled(self):
        order={**self.ready,"order_status":"CANCELADO",
               "logistics":[{"status":"ARRIVED_IQUIQUE","pickup_status":"pending"}]}
        self.assertEqual(self.fn(order,self.asset,[],True),"")

    def test_old_completed_picked_up(self):
        self.assertEqual(self.fn(self.ready,self.asset,[{"history_scope":"current"}],True),"completed_picked_up")

    def test_long_history_share_protects(self):
        self.assertEqual(self.fn(self.ready,self.asset,[{"history_scope":"all"}],True),"")
        self.assertEqual(self.fn(self.ready,self.asset,[{"history_scope":"12m"}],True),"")

    def test_unknown_pickup_never_deletes(self):
        order={**self.ready,"logistics":[]}
        self.assertEqual(self.fn(order,self.asset,[{"history_scope":"current"}],True),"")

    def test_incomplete_workflow_never_deletes(self):
        order={**self.ready,"workflows":[{"status":"EN_PROCESO"}]}
        self.assertEqual(self.fn(order,self.asset,[{"history_scope":"current"}],True),"")

    def test_missing_share_requires_local_proof_at_execute(self):
        self.assertEqual(self.fn(self.ready,self.asset,[],True),"no_active_share")
        self.assertIn('if expected != evidence',SOURCE)

    def test_default_execute_disabled_and_uppercase_delete(self):
        self.assertIn('os.environ.get("ORDER_B2_CLEANUP_ENABLED")!="1"',SOURCE)
        self.assertIn('if body.get("word")!="DELETE":',SOURCE)
        self.assertIn('_PLANS.pop(token, None)',SOURCE)

    def test_no_legacy_destructive_routes(self):
        self.assertNotIn("admin-delete",SOURCE)
        self.assertNotIn("DELETE FROM cloud_assets",SOURCE)
        self.assertIn("UPDATE cloud_assets SET active=FALSE",SOURCE)
        self.assertIn("list_object_versions",SOURCE)


if __name__=="__main__":
    unittest.main()
