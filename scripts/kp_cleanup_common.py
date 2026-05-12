"""KP 清洗决策的共享逻辑（提案脚本与迁移脚本共用）。"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Sequence

from sqlalchemy import text

# 必须与 kp_skeleton_audit.py 的粒度规则一致


def classify_grain(name: str) -> str:
    if re.search(r"(的定义|的概念|的含义|什么是)", name):
        return "概念定义"
    if re.search(r"(公式|定理|法则)", name):
        return "公式定理"
    if re.search(r"(方法|思路|步骤|策略|技巧)", name):
        return "解题方法"
    if re.search(r"(性质|特点|特征|规律)", name):
        return "性质规律"
    if re.search(r"(判定|判断|辨析|识别|证明)", name):
        return "判定/识别"
    if re.search(r"(运算|计算|求解|化简|求|解)", name):
        return "运算/计算"
    if re.search(r"(应用|结合|综合)", name):
        return "应用/综合"
    if re.search(r"(易错|误区|陷阱|注意|常见错)", name):
        return "易错点"
    if re.search(r"(关系|结构|分类)", name):
        return "结构关系"
    if re.search(r"[∀∃∈⊆⊇⇒⇔]", name) or re.search(r"[a-zA-Z]\([a-zA-Z]+\)", name):
        return "符号公式型"
    return "纯概念名词"


GRAIN_DEMOTABLE = {
    "解题方法",
    "判定/识别",
    "运算/计算",
    "性质规律",
    "应用/综合",
    "符号公式型",
}


def extract_core(name: str) -> str:
    n = re.sub(r"[（(][^）)]*[）)]", "", name or "")
    n = re.sub(r"[，,；;].*$", "", n)
    n = re.sub(
        r"(的判定|的运算|的计算|的求解|的应用|的判断|的化简|的证明|"
        r"的概念|的定义|的方法|的思路|的规则|的规律|的性质|的特点)$",
        "",
        n,
    )
    n = re.sub(r"[\s]+", "", n)
    n = re.sub(r"[∀∃∈∉⊆⊇⊂⊃∪∩⇒⇔≤≥≠≈]", "", n)
    return n


def detect_has_trgm(session) -> bool:
    return bool(
        session.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")).scalar(),
    )


def find_parent_kp(
    session,
    *,
    name: str,
    exclude_id: int,
    kp_rows: Sequence[Any],
    has_trgm: bool,
    allowed_parent_ids: set[int] | None = None,
) -> tuple[int | None, float, str]:
    """在 KP 中为 DEMOTE 找父节点。allowed_parent_ids 非空则只从这些 id 中选。"""
    if not name:
        return None, 0.0, ""

    def ok_parent(cid: int) -> bool:
        return allowed_parent_ids is None or cid in allowed_parent_ids

    candidates: list[tuple[int, str, float]] = []
    if has_trgm:
        rows = session.execute(
            text("""
            SELECT id, canonical_name, similarity(canonical_name, :n) AS sim
            FROM knowledge_points
            WHERE id <> :ex
            ORDER BY canonical_name <-> :n
            LIMIT 20
        """),
            {"n": name, "ex": exclude_id},
        ).all()
        candidates = [(r[0], r[1] or "", float(r[2] or 0)) for r in rows if ok_parent(r[0])]
    else:
        def trigrams(s: str) -> set[str]:
            s = f"  {s}  "
            return {s[i : i + 3] for i in range(len(s) - 2)}

        my_grams = trigrams(name)
        scored: list[tuple[int, str, float]] = []
        for rr in kp_rows:
            cid = rr[0]
            if cid == exclude_id or not ok_parent(cid):
                continue
            other_name = rr[1] or ""
            if not other_name:
                continue
            other_grams = trigrams(other_name)
            uni = len(my_grams | other_grams)
            sim = (len(my_grams & other_grams) / uni) if uni else 0.0
            scored.append((cid, other_name, sim))
        scored.sort(key=lambda x: -x[2])
        candidates = scored[:12]

    for cid, cname, sim in candidates:
        cand_grain = classify_grain(cname)
        if cand_grain not in {"纯概念名词", "概念定义", "公式定理", "结构关系"}:
            continue
        if cname and cname in name:
            return cid, sim, cname

    for cid, cname, sim in candidates:
        cand_grain = classify_grain(cname)
        if cand_grain in {"纯概念名词", "概念定义", "公式定理", "结构关系"}:
            return cid, sim, cname

    if candidates:
        return candidates[0][0], candidates[0][2], candidates[0][1]
    return None, 0.0, ""


def kp_ids_marked_removed(decisions: list[dict]) -> set[int]:
    removed: set[int] = set()
    for d in decisions:
        act = str(d["proposed_action"])
        if act in ("DELETE_ORPHAN", "DELETE_EMPTY_IN_PKG", "MERGE_INTO_CANONICAL", "DEMOTE_TO_ATOM"):
            removed.add(int(d["id"]))
    return removed


def survivor_kp_ids(decisions: list[dict]) -> set[int]:
    return {int(d["id"]) for d in decisions} - kp_ids_marked_removed(decisions)


def fix_demote_parents(
    session,
    *,
    decisions: list[dict],
    kps_rows: Sequence[Any],
    has_trgm: bool,
) -> None:
    """就地修正 DEMOTE 的 parent：不得指向在本次迁移中被删除的 KP。"""
    alive = survivor_kp_ids(decisions)
    for d in decisions:
        if str(d["proposed_action"]) != "DEMOTE_TO_ATOM":
            continue
        kid = int(d["id"])
        name = str(d["name"])
        pid_str = str(d["proposed_parent_kp_id"] or "").strip()
        pid = int(pid_str) if pid_str.isdigit() else None
        if pid is None or pid not in alive or pid == kid:
            new_pid, sim, pname = find_parent_kp(
                session,
                name=name,
                exclude_id=kid,
                kp_rows=kps_rows,
                has_trgm=has_trgm,
                allowed_parent_ids=alive - {kid},
            )
            d["proposed_parent_kp_id"] = new_pid or ""
            d["proposed_parent_kp_name"] = pname or ""
            d["parent_similarity"] = f"{sim:.2f}" if sim else ""
            if new_pid:
                d["reason"] = (
                    f"{d['reason']}；已自动将父 KP 校正为幸存者池中的 #{new_pid}"
                )


def build_kp_cleanup_decisions(session) -> tuple[list[dict], Counter, int]:
    """返回 (decisions, action_counter, kp_total)。"""

    kps = session.execute(
        text("""
        SELECT id, canonical_name, subject, grade_scope, knowledge_type,
               coalesce(canonical_summary,'') AS summary,
               coalesce(aliases_json::text,'') AS aliases_json,
               source_origin, created_at
        FROM knowledge_points
        ORDER BY id
        """),
    ).all()

    kp_total = len(kps)

    active_kp_ids = {r[0] for r in session.execute(text("SELECT DISTINCT knowledge_point_id FROM knowledge_package_points")).all()}
    active_pkg_of_kp: dict[int, list[int]] = defaultdict(list)
    for r in session.execute(text("SELECT knowledge_point_id, package_id FROM knowledge_package_points")).all():
        active_pkg_of_kp[r[0]].append(r[1])

    block_count = dict(
        session.execute(
            text("""
                SELECT knowledge_point_id, COUNT(*) FROM knowledge_blocks
                WHERE knowledge_point_id IS NOT NULL GROUP BY knowledge_point_id
            """),
        ).all(),
    )
    atom_count = dict(
        session.execute(
            text("""
                SELECT knowledge_point_id, COUNT(*) FROM knowledge_atoms
                WHERE knowledge_point_id IS NOT NULL GROUP BY knowledge_point_id
            """),
        ).all(),
    )
    kql_count = dict(
        session.execute(
            text("""
                SELECT knowledge_point_id, COUNT(*) FROM knowledge_question_links GROUP BY knowledge_point_id
            """),
        ).all(),
    )
    prov_count = dict(
        session.execute(
            text("""
                SELECT knowledge_point_id, COUNT(*) FROM knowledge_point_provenance GROUP BY knowledge_point_id
            """),
        ).all(),
    )
    ege_out = dict(
        session.execute(
            text("""
                SELECT source_entity_id, COUNT(*) FROM entity_graph_edges
                WHERE source_entity_type='knowledge_point' GROUP BY source_entity_id
            """),
        ).all(),
    )
    ege_in = dict(
        session.execute(
            text("""
                SELECT target_entity_id, COUNT(*) FROM entity_graph_edges
                WHERE target_entity_type='knowledge_point' GROUP BY target_entity_id
            """),
        ).all(),
    )

    cores: dict[str, list[int]] = defaultdict(list)
    core_of_kp: dict[int, str] = {}
    for r in kps:
        core = extract_core(r[1] or "")
        cores[core].append(r[0])
        core_of_kp[r[0]] = core

    canonical_of_cluster: dict[str, int] = {}
    for core, members in cores.items():
        if len(members) < 2 or core == "":
            continue

        def score(cid: int) -> tuple:
            has_evidence = block_count.get(cid, 0) > 0 or atom_count.get(cid, 0) > 0
            kp_row = next(x for x in kps if x[0] == cid)
            return (0 if has_evidence else 1, len(kp_row[1] or ""), cid)

        canonical_of_cluster[core] = min(members, key=score)

    has_trgm = detect_has_trgm(session)
    decisions: list[dict] = []
    action_counter: Counter[str] = Counter()

    # cols: id, canonical_name, subject, grade_scope, knowledge_type, summary,
    #       aliases_json, source_origin, created_at
    for r in kps:
        kid = int(r[0])
        name = (r[1] or "").strip()
        subject, grade, ktype = r[2], r[3], r[4]
        summary = r[5] or ""
        _ = r[6]  # aliases_json kept in SQL shape for callers using full row elsewhere

        in_active = kid in active_kp_ids
        bk = block_count.get(kid, 0)
        at = atom_count.get(kid, 0)
        kq = kql_count.get(kid, 0)
        pv = prov_count.get(kid, 0)
        eg = ege_out.get(kid, 0) + ege_in.get(kid, 0)

        core = core_of_kp[kid]
        cluster_members = cores.get(core, [])
        in_cluster = len(cluster_members) >= 2 and core != ""
        cluster_canonical = canonical_of_cluster.get(core) if in_cluster else None
        is_canonical = cluster_canonical == kid if in_cluster else False
        grain = classify_grain(name)

        parent_kp_id: int | None = None
        parent_kp_name = ""
        parent_sim = 0.0
        reason = ""
        action = ""

        if (not in_active) and bk == 0 and at == 0 and kq == 0:
            action = "DELETE_ORPHAN"
            reason = "不属于任何活包；无 KQL 桥接；无 atom/block 承载；删除安全"
        elif in_active and bk == 0 and at == 0 and kq == 0 and pv == 0:
            action = "DELETE_EMPTY_IN_PKG"
            reason = f"在包 {active_pkg_of_kp[kid]} 内但 0 atom/0 block/0 KQL/0 provenance，是 LLM 凭空抽取的空壳"
        elif in_cluster and not is_canonical:
            action = "MERGE_INTO_CANONICAL"
            cn = next((rr for rr in kps if rr[0] == cluster_canonical), None)
            canon_name = cn[1] if cn else "?"
            parent_kp_id = cluster_canonical
            parent_kp_name = canon_name or ""
            reason = (
                f"与 #{cluster_canonical} '{canon_name}' 共享核心词 '{core}'；"
                f"建议把当前名字 '{name}' 收入其 aliases，引用迁移到 #{cluster_canonical}"
            )
        elif grain in GRAIN_DEMOTABLE:
            if kq > 0 or bk > 0 or at > 0:
                parent_kp_id, parent_sim, parent_kp_name = find_parent_kp(
                    session,
                    name=name,
                    exclude_id=kid,
                    kp_rows=kps,
                    has_trgm=has_trgm,
                    allowed_parent_ids=None,
                )
                action = "DEMOTE_TO_ATOM"
                if parent_kp_id:
                    reason = (
                        f"粒度=「{grain}」，本质是动作/方法/性质，不是概念；"
                        f"建议作为 atom 挂到 #{parent_kp_id} '{parent_kp_name}' 下"
                        f"（相似度={parent_sim:.2f}）；保留 KQL/atom 关系"
                    )
                else:
                    reason = (
                        f"粒度=「{grain}」，应降级为 atom；但未找到合适父 KP，需人工指定 parent_concept"
                    )
            else:
                action = "DELETE_EMPTY_IN_PKG" if in_active else "DELETE_ORPHAN"
                reason = f"粒度=「{grain}」属于动作类；且无任何承载，删除"
        elif in_cluster and is_canonical:
            action = "KEEP_AS_CANONICAL"
            n_other = len(cluster_members) - 1
            reason = (
                f"簇 '{core}' 的代表，将接收 {n_other} 个簇内别名；承载情况：block={bk} atom={at} KQL={kq}"
            )
        else:
            action = "KEEP"
            reason = f"粒度=「{grain}」，是真正的概念名词；承载：block={bk} atom={at} KQL={kq}"

        summar = summary if isinstance(summary, str) else ""
        summ_exc = summar[:50] + "…" if summar and len(summar) > 50 else summar

        dec = {
            "id": kid,
            "name": name,
            "subject": subject or "",
            "grade_scope": grade or "",
            "knowledge_type": ktype or "",
            "in_active_pkg": "Y" if in_active else "N",
            "active_pkg_ids": ",".join(map(str, active_pkg_of_kp.get(kid, []))),
            "block_count": bk,
            "atom_count": at,
            "kql_count": kq,
            "provenance_count": pv,
            "ege_count": eg,
            "core_word": core,
            "cluster_size": len(cluster_members) if in_cluster else 1,
            "cluster_canonical_id": cluster_canonical or "",
            "is_canonical": "Y" if is_canonical else "",
            "grain_class": grain,
            "proposed_action": action,
            "proposed_parent_kp_id": parent_kp_id or "",
            "proposed_parent_kp_name": parent_kp_name or "",
            "parent_similarity": f"{parent_sim:.2f}" if parent_sim else "",
            "reason": reason,
            "summary_excerpt": summ_exc,
        }

        decisions.append(dec)
        action_counter[action] += 1

    fix_demote_parents(session, decisions=decisions, kps_rows=kps, has_trgm=has_trgm)

    for d in decisions:
        if str(d["proposed_action"]) == "DEMOTE_TO_ATOM" and (
            not str(d["proposed_parent_kp_id"] or "").strip()
        ):
            grain = str(d["grain_class"])
            has_load = (
                int(d["block_count"]) > 0 or int(d["atom_count"]) > 0 or int(d["kql_count"]) > 0
            )
            if has_load:
                # 有 KQL/atom/block 承载，绝不能删；保留为 KEEP 等待人工指派父概念
                d["proposed_action"] = "KEEP"
                d[
                    "reason"
                ] = (
                    f"粒度=「{grain}」本应 DEMOTE，但未找到幸存者父 KP；"
                    f"承载 KQL={d['kql_count']} block={d['block_count']} atom={d['atom_count']}，"
                    "保留为 KP 待人工指派父概念"
                )
            else:
                act = "DELETE_EMPTY_IN_PKG" if d["in_active_pkg"] == "Y" else "DELETE_ORPHAN"
                d["proposed_action"] = act
                d["reason"] = f"粒度=「{grain}」需降级但未找到幸存者父 KP；无承载，兜底改为 {act}"

    action_counter.clear()
    for d in decisions:
        action_counter[str(d["proposed_action"])] += 1

    return decisions, action_counter, kp_total


def load_decisions_from_csv(rows: list[dict]) -> list[dict]:
    """CSV 读入后列名已为 id / proposed_parent_kp_id 等时，转成与 build 一致的 int 计数列。"""
    out: list[dict] = []
    for raw in rows:
        d = dict(raw)
        d["id"] = int(float(d["id"])) if isinstance(d["id"], str) and d["id"].replace(".", "").isdigit() else int(d["id"])
        pp = str(d.get("proposed_parent_kp_id") or "").strip()
        if pp.endswith(".0"):
            pp = pp[:-2]
        d["proposed_parent_kp_id"] = int(pp) if pp.isdigit() else ""
        cc = str(d.get("cluster_canonical_id") or "").strip()
        if cc.endswith(".0"):
            cc = cc[:-2]
        d["cluster_canonical_id"] = int(cc) if cc.isdigit() else cc
        for k in ("block_count", "atom_count", "kql_count", "provenance_count", "ege_count", "cluster_size"):
            if k in d and d[k] != "":
                try:
                    d[k] = int(float(d[k]))
                except ValueError:
                    pass
        out.append(d)
    return out


def filter_allowed_actions(rows: list[dict], actions: frozenset[str] | None) -> list[dict]:
    """仅保留给定动作的行；KEEP* 永远不执行写操作此处只用于统计。"""
    if not actions:
        return rows
    return [r for r in rows if str(r["proposed_action"]) in actions]
