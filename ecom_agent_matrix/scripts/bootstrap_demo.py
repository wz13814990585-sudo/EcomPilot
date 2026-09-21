"""Idempotently install the Northstar Outdoor local demo and knowledge corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from ..db.base import AsyncPGClient
from ..db.redis_client import AsyncRedisClient
from ..infrastructure.embedding.provider import get_text_embeddings_batch
from ..modules.rag.preprocessor import clean_text, split_chunk
from .init_db import execute_sql_file

TENANT = "demo_tenant"
STORE = "demo_store"
STORE_NAME = "Northstar Outdoor"

PRODUCTS = (
    ("BAG-001", "bags", 79.0, 120, "TrailDry Waterproof Daypack", "TrailDry 防水户外背包"),
    ("BAG-002", "bags", 99.0, 8, "SummitPro Travel Backpack", "SummitPro 旅行背包"),
    ("BAG-003", "bags", 59.0, 0, "CityLite Sling Bag", "CityLite 轻便斜挎包"),
    ("LAMP-001", "outdoor", 49.0, 16, "Solar Camp Lantern", "太阳能露营灯"),
    ("LAMP-002", "outdoor", 35.0, 90, "Pocket Trail Lamp", "便携式小径灯"),
    ("BOTTLE-001", "outdoor", 29.0, 180, "Insulated Steel Bottle", "保温不锈钢水瓶"),
    ("BOTTLE-002", "outdoor", 24.0, 21, "Collapsible Travel Bottle", "可折叠旅行水瓶"),
    ("TENT-001", "outdoor", 189.0, 7, "Two Person Cloud Tent", "双人轻量云帐"),
    ("TENT-002", "outdoor", 279.0, 32, "Family Ridge Tent", "家庭山脊帐篷"),
    ("CHARGER-001", "electronics", 99.0, 11, "65W Travel Charger", "65W 旅行充电器"),
    ("CHARGER-002", "electronics", 45.0, 140, "Solar Power Bank", "太阳能移动电源"),
    ("CAMERA-001", "electronics", 129.0, 4, "Trail Action Camera", "户外运动相机"),
    ("SPEAKER-001", "electronics", 69.0, 54, "Water Resistant Speaker", "户外防泼水音箱"),
    ("HOME-001", "home", 39.0, 88, "Portable Picnic Blanket", "便携野餐垫"),
    ("HOME-002", "home", 55.0, 13, "Rechargeable Desk Light", "充电护眼台灯"),
    ("HOME-003", "home", 32.0, 75, "Travel Storage Cubes", "旅行收纳袋组"),
    ("BEAUTY-001", "beauty", 28.0, 9, "Mineral Sun Stick", "矿物防晒棒"),
    ("BEAUTY-002", "beauty", 22.0, 105, "After Sun Gel", "晒后修护凝胶"),
    ("BEAUTY-003", "beauty", 18.0, 64, "Travel Skin Kit", "旅行护肤套装"),
    ("ACC-001", "accessories", 25.0, 200, "UV Trail Hat", "UPF50 户外遮阳帽"),
    ("ACC-002", "accessories", 19.0, 6, "Quick Dry Towel", "速干旅行毛巾"),
    ("ACC-003", "accessories", 42.0, 47, "Polarized Sunglasses", "偏光户外墨镜"),
    ("ACC-004", "accessories", 16.0, 160, "Waterproof Phone Pouch", "防水手机袋"),
    ("ACC-005", "accessories", 14.0, 23, "Compact First Aid Kit", "便携急救包"),
    ("COOK-001", "camp_kitchen", 58.0, 42, "Compact Camp Stove", "便携式露营炉"),
    ("COOK-002", "camp_kitchen", 36.0, 18, "Titanium Cook Set", "钛合金户外锅具"),
    ("COOK-003", "camp_kitchen", 21.0, 96, "Insulated Camp Mug", "保温露营杯"),
    ("SLEEP-001", "sleep_system", 119.0, 14, "Ultralight Sleeping Bag", "超轻保暖睡袋"),
    ("SLEEP-002", "sleep_system", 72.0, 28, "Self Inflating Mat", "自充气睡垫"),
    ("SLEEP-003", "sleep_system", 34.0, 67, "Packable Travel Pillow", "可压缩旅行枕"),
    ("HIKE-001", "hiking", 89.0, 31, "Carbon Trekking Poles", "碳纤维登山杖"),
    ("HIKE-002", "hiking", 46.0, 12, "Trail Gaiters", "防泥沙徒步鞋套"),
    ("HIKE-003", "hiking", 27.0, 83, "Merino Hiking Socks", "美利奴徒步袜"),
    ("RAIN-001", "rainwear", 109.0, 19, "StormShell Rain Jacket", "StormShell 防雨夹克"),
    ("RAIN-002", "rainwear", 44.0, 58, "Packable Rain Poncho", "便携式防雨斗篷"),
    ("TECH-001", "electronics", 139.0, 22, "GPS Trail Watch", "GPS 户外运动手表"),
    ("TECH-002", "electronics", 64.0, 37, "Emergency Radio", "太阳能应急收音机"),
    ("TECH-003", "electronics", 31.0, 71, "Waterproof Headlamp", "防水头灯"),
    ("PET-001", "pet_outdoor", 52.0, 26, "Trail Dog Harness", "户外犬用胸背带"),
    ("PET-002", "pet_outdoor", 23.0, 49, "Collapsible Pet Bowl", "折叠宠物碗套装"),
    ("KIDS-001", "kids_outdoor", 42.0, 35, "Kids Explorer Backpack", "儿童探索背包"),
    ("KIDS-002", "kids_outdoor", 18.0, 92, "Kids Sun Explorer Hat", "儿童防晒探险帽"),
    ("TRAVEL-001", "travel", 68.0, 24, "Carry On Travel Duffel", "随身旅行圆筒包"),
    ("TRAVEL-002", "travel", 26.0, 116, "RFID Passport Organizer", "RFID 护照收纳包"),
    ("TRAVEL-003", "travel", 17.0, 150, "Digital Luggage Scale", "电子行李秤"),
    ("CYCLE-001", "cycling", 76.0, 17, "Commuter Bike Pannier", "通勤自行车驮包"),
    ("CYCLE-002", "cycling", 33.0, 63, "Rechargeable Bike Light", "充电式自行车灯"),
    ("CYCLE-003", "cycling", 29.0, 44, "Compact Bike Repair Kit", "便携自行车维修套装"),
    (
        "SHOE-001",
        "footwear",
        129.0,
        36,
        "TrailForge Waterproof Hiking Shoes",
        "TrailForge 防水徒步鞋",
    ),
    ("SHOE-002", "footwear", 98.0, 12, "RidgeRun Trail Running Shoes", "RidgeRun 越野跑鞋"),
    ("SHOE-003", "footwear", 64.0, 58, "CoastWalk Outdoor Sandals", "CoastWalk 户外凉鞋"),
    ("SHOE-004", "footwear", 55.0, 21, "Junior Trek Adventure Shoes", "Junior Trek 儿童探险鞋"),
)


async def _schema() -> None:
    sql_dir = Path(__file__).resolve().parents[1] / "db"
    await execute_sql_file(sql_dir / "business_tables.sql")
    await execute_sql_file(sql_dir / "vector_tables.sql")


async def _clear_demo() -> None:
    for table in (
        "vector_goods_kb",
        "agent_long_memory",
        "risk_record",
        "competitor_price",
        "ecom_order",
        "ecom_goods",
    ):
        await AsyncPGClient.execute_sql(
            f"DELETE FROM {table} WHERE tenant_id=%s AND store_id=%s", [TENANT, STORE]
        )


async def _seed_products() -> None:
    for sku, category, price, stock, title_en, title_zh in PRODUCTS:
        await AsyncPGClient.execute_sql(
            """
            INSERT INTO ecom_goods
              (tenant_id,store_id,sku,category,price,stock_num,title_en,title_zh,title_es,title_fr,
               desc_multi,cost_price,reorder_level,supplier,status,tags,
               store_name,is_demo,create_time,update_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,true,%s,%s)
            ON CONFLICT (tenant_id,store_id,sku) DO UPDATE SET
              category=EXCLUDED.category,price=EXCLUDED.price,stock_num=EXCLUDED.stock_num,
              title_en=EXCLUDED.title_en,title_zh=EXCLUDED.title_zh,
              desc_multi=EXCLUDED.desc_multi,cost_price=EXCLUDED.cost_price,
              reorder_level=EXCLUDED.reorder_level,supplier=EXCLUDED.supplier,
              status=EXCLUDED.status,tags=EXCLUDED.tags,
              store_name=EXCLUDED.store_name,update_time=EXCLUDED.update_time
            """,
            [
                TENANT,
                STORE,
                sku,
                category,
                price,
                stock,
                title_en,
                title_zh,
                title_en,
                title_en,
                f"{title_zh}。适用于跨境独立站商品搜索、库存、利润和运营分析演示，SKU {sku}。",
                round(price * 0.43, 2),
                20 if price < 100 else 10,
                f"Northstar Supplier {(category[:1] or 'G').upper()}",
                [category, "demo", "outdoor"],
                STORE_NAME,
                datetime(2026, 5, 1),
                datetime(2026, 9, 20),
            ],
        )


async def _seed_orders() -> None:
    skus = [item[0] for item in PRODUCTS]
    # 2026-09 之后的未来订单会污染“近 7/30 天”报表。因此用 1‑9 月
    # 的高密度历史数据保持 720 条总量，并保留 7 月 10% -> 8 月 30% 的退款异常。
    refund_targets = {1: 7, 2: 5, 3: 8, 4: 7, 5: 6, 6: 7, 7: 8, 8: 24, 9: 9}
    statuses = ("delivered", "shipped", "processing", "delivered")
    countries = ("AU", "US", "GB", "CA", "DE", "FR")
    for month in range(1, 10):
        refund_count = refund_targets[month]
        for index in range(80):
            if month == 8 and index < refund_count:
                sku = "BAG-002" if index < 11 else "CHARGER-001"
            else:
                sku = skus[(index * 5 + month) % len(skus)]
            product = next(item for item in PRODUCTS if item[0] == sku)
            quantity = 1 + (index % 3)
            # 9 月数据截止在 20 日，避免当前时钟下出现未来交易。
            created = datetime(2026, month, 1) + timedelta(hours=index * (6 if month == 9 else 8))
            await AsyncPGClient.execute_sql(
                """
                INSERT INTO ecom_order
                  (tenant_id,store_id,order_no,sku,buy_num,total_amount,refund_flag,create_time,
                   status,customer_name,country,payment_status,fulfillment_status,tracking_no)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'paid',%s,%s)
                ON CONFLICT (tenant_id,store_id,order_no) DO UPDATE SET
                  sku=EXCLUDED.sku,buy_num=EXCLUDED.buy_num,total_amount=EXCLUDED.total_amount,
                  refund_flag=EXCLUDED.refund_flag,create_time=EXCLUDED.create_time,
                  status=EXCLUDED.status,customer_name=EXCLUDED.customer_name,country=EXCLUDED.country,
                  payment_status=EXCLUDED.payment_status,
                  fulfillment_status=EXCLUDED.fulfillment_status,tracking_no=EXCLUDED.tracking_no
                """,
                [
                    TENANT,
                    STORE,
                    f"ORD-DEMO-2026{month:02d}-{index + 1:03d}",
                    sku,
                    quantity,
                    round(product[2] * quantity, 2),
                    index < refund_count,
                    created,
                    "refund_requested" if index < refund_count else statuses[index % len(statuses)],
                    f"Demo Customer {month:02d}-{index + 1:03d}",
                    countries[(index + month) % len(countries)],
                    "held" if index < refund_count else "fulfilled",
                    f"NS{month:02d}{index + 1:06d}" if index % 4 != 2 else "",
                ],
            )


async def _seed_competitor_and_risk() -> None:
    platforms = ("Amazon", "Temu", "AliExpress", "eBay")
    for index, product in enumerate(PRODUCTS[:40]):
        for offset, platform in enumerate(platforms):
            factor = (0.82, 0.76, 0.88, 1.08)[offset] + (index % 3) * 0.03
            await AsyncPGClient.execute_sql(
                """INSERT INTO competitor_price
                (tenant_id,store_id,target_sku,competitor_name,compete_price,crawl_time)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                [
                    TENANT,
                    STORE,
                    product[0],
                    platform,
                    round(product[2] * factor, 2),
                    datetime(2026, 9, 15) + timedelta(hours=index + offset),
                ],
            )
    risks = (
        ("ORD-DEMO-RISK", "high_value", "高金额且购买数量异常，需人工复核"),
        ("ORD-DEMO-REFUND", "refund_review", "退款申请需核验商品状态"),
        ("ORD-DEMO-202608-001", "refund_cluster", "BAG-002 退款集中"),
        ("ORD-DEMO-202608-002", "quantity_outlier", "购买数量偏高"),
        ("ORD-DEMO-202608-003", "price_anomaly", "成交额偏离商品价格"),
        ("ORD-DEMO-202608-004", "manual_review", "演示人工复核订单"),
        ("ORD-DEMO-202608-005", "velocity", "短时间高频下单"),
        ("ORD-DEMO-202608-006", "address_check", "收货信息需人工核对"),
        ("ORD-DEMO-202608-007", "payment_review", "支付行为与历史模式不一致"),
        ("ORD-DEMO-202608-008", "device_mismatch", "登录设备发生异常变化"),
        ("ORD-DEMO-202611-014", "promotion_abuse", "优惠券使用频率异常"),
        ("ORD-DEMO-202612-021", "reship_review", "重复补发申请需复核"),
    )
    for index, row in enumerate(risks):
        await AsyncPGClient.execute_sql(
            """INSERT INTO risk_record
            (tenant_id,store_id,order_no,risk_type,risk_desc,create_time)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            [TENANT, STORE, *row, datetime(2026, 8, 20) + timedelta(days=index)],
        )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.6f}" for value in vector) + "]"


async def _ingest_knowledge(with_embeddings: bool) -> tuple[int, int, str]:
    root = Path(__file__).resolve().parents[2] / "demo" / "knowledge"
    records: list[tuple[str, str, dict]] = []
    for path in sorted(root.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        title = raw.splitlines()[0].lstrip("# ").strip()
        for chunk_index, chunk in enumerate(split_chunk(clean_text(raw))):
            metadata = {
                "document_id": path.stem,
                "title": title,
                "source": str(path.relative_to(root.parent.parent)),
                "category": path.stem.split("_", 1)[1],
                "language": "zh",
                "effective_date": "2026-09-01",
                "tenant_id": TENANT,
                "store_id": STORE,
                "chunk_id": f"{path.stem}:{chunk_index}",
            }
            sku = next((item[0] for item in PRODUCTS if item[0] in raw), path.stem.upper())
            records.append((sku, chunk, metadata))
    vectors: list[list[float] | None] = [None] * len(records)
    mode = "lexical_only"
    if with_embeddings:
        try:
            vectors = await get_text_embeddings_batch([record[1] for record in records])
            mode = "hybrid"
        except Exception as exc:
            print(f"⚠️  Embedding unavailable ({type(exc).__name__}); using lexical-only RAG")
    for (sku, chunk, metadata), vector in zip(records, vectors, strict=True):
        if vector is None:
            await AsyncPGClient.execute_sql(
                """INSERT INTO vector_goods_kb
                (tenant_id,store_id,goods_sku,lang,chunk_text,embedding,meta_json)
                VALUES (%s,%s,%s,'zh',%s,NULL,%s::jsonb)""",
                [TENANT, STORE, sku, chunk, json.dumps(metadata, ensure_ascii=False)],
            )
        else:
            await AsyncPGClient.execute_sql(
                """INSERT INTO vector_goods_kb
                (tenant_id,store_id,goods_sku,lang,chunk_text,embedding,meta_json)
                VALUES (%s,%s,%s,'zh',%s,%s::vector,%s::jsonb)""",
                [
                    TENANT,
                    STORE,
                    sku,
                    chunk,
                    _vector_literal(vector),
                    json.dumps(metadata, ensure_ascii=False),
                ],
            )
    return len(list(root.glob("*.md"))), len(records), mode


async def bootstrap(with_embeddings: bool = False) -> dict[str, object]:
    await AsyncPGClient.execute_sql("SELECT 1")
    redis = await AsyncRedisClient.get_client()
    await redis.ping()
    await _schema()
    await _clear_demo()
    await _seed_products()
    await _seed_orders()
    await _seed_competitor_and_risk()
    documents, chunks, mode = await _ingest_knowledge(with_embeddings)
    counts = await AsyncPGClient.execute_sql(
        """SELECT
        (SELECT COUNT(*) FROM ecom_goods WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM ecom_order WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM competitor_price WHERE tenant_id=%s AND store_id=%s),
        (SELECT COUNT(*) FROM risk_record WHERE tenant_id=%s AND store_id=%s)""",
        [TENANT, STORE] * 4,
    )
    result = {
        "products": counts[0][0],
        "orders": counts[0][1],
        "competitor_records": counts[0][2],
        "risk_records": counts[0][3],
        "rag_documents": documents,
        "rag_chunks": chunks,
        "retrieval_mode": mode,
        "business_api_orders": 4,
        "business_api_campaigns": 4,
        "tenant": TENANT,
        "store": STORE,
    }
    await AsyncPGClient.close()
    await AsyncRedisClient.close()
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap the Northstar Outdoor demo")
    parser.add_argument("--with-embeddings", action="store_true")
    args = parser.parse_args()
    result = await bootstrap(with_embeddings=args.with_embeddings)
    print("\nDemo bootstrap complete")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
