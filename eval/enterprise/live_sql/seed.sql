CREATE TABLE IF NOT EXISTS ecom_goods (
  id bigint PRIMARY KEY,
  tenant_id varchar NOT NULL,
  store_id varchar NOT NULL,
  sku varchar NOT NULL,
  category varchar NOT NULL,
  price numeric(12,2) NOT NULL,
  stock_num integer NOT NULL,
  title_zh text,
  title_en text,
  store_name varchar,
  create_time timestamp NOT NULL,
  UNIQUE (tenant_id, store_id, sku)
);
CREATE TABLE IF NOT EXISTS ecom_order (
  id bigint PRIMARY KEY,
  tenant_id varchar NOT NULL,
  store_id varchar NOT NULL,
  order_no varchar NOT NULL,
  sku varchar NOT NULL,
  buy_num integer NOT NULL,
  total_amount numeric(12,2) NOT NULL,
  refund_flag boolean NOT NULL,
  create_time timestamp NOT NULL,
  FOREIGN KEY (tenant_id, store_id, sku)
    REFERENCES ecom_goods (tenant_id, store_id, sku)
);
CREATE TABLE IF NOT EXISTS competitor_price (
  id bigint PRIMARY KEY,
  tenant_id varchar NOT NULL,
  store_id varchar NOT NULL,
  target_sku varchar NOT NULL,
  competitor_name varchar NOT NULL,
  compete_price numeric(12,2) NOT NULL,
  crawl_time timestamp NOT NULL,
  FOREIGN KEY (tenant_id, store_id, target_sku)
    REFERENCES ecom_goods (tenant_id, store_id, sku)
);
TRUNCATE TABLE competitor_price, ecom_order, ecom_goods;
INSERT INTO ecom_goods VALUES
  (1,'tenant-a','store-a','SKU-A','electronics',100,30,'A','A','Seed Store','2026-07-01'),
  (2,'tenant-a','store-a','SKU-B','electronics',50,5,'B','B','Seed Store','2026-07-01'),
  (3,'tenant-a','store-a','SKU-C','home',80,20,'C','C','Seed Store','2026-07-01'),
  (4,'tenant-a','store-a','SKU-D','beauty',30,0,'D','D','Seed Store','2026-07-01'),
  (101,'tenant-b','store-b','SKU-SECRET','secret',999,99,'Secret','Secret','Other Store','2026-08-01');
INSERT INTO ecom_order VALUES
  (1,'tenant-a','store-a','JUL-001','SKU-A',1,100,true,'2026-07-03'),
  (2,'tenant-a','store-a','JUL-002','SKU-A',1,100,false,'2026-07-08'),
  (3,'tenant-a','store-a','JUL-003','SKU-B',1,50,false,'2026-07-10'),
  (4,'tenant-a','store-a','JUL-004','SKU-B',2,100,false,'2026-07-17'),
  (5,'tenant-a','store-a','JUL-005','SKU-C',1,80,true,'2026-07-24'),
  (6,'tenant-a','store-a','AUG-001','SKU-A',1,100,true,'2026-08-02'),
  (7,'tenant-a','store-a','AUG-002','SKU-A',2,200,true,'2026-08-05'),
  (8,'tenant-a','store-a','AUG-003','SKU-B',1,50,true,'2026-08-09'),
  (9,'tenant-a','store-a','AUG-004','SKU-B',1,50,false,'2026-08-12'),
  (10,'tenant-a','store-a','AUG-005','SKU-C',1,80,false,'2026-08-15'),
  (11,'tenant-a','store-a','AUG-006','SKU-C',2,160,true,'2026-08-19'),
  (12,'tenant-a','store-a','AUG-007','SKU-D',1,30,true,'2026-08-22'),
  (13,'tenant-a','store-a','AUG-008','SKU-D',2,60,false,'2026-08-28'),
  (14,'tenant-a','store-a','SEP-001','SKU-A',1,100,false,'2026-09-04'),
  (15,'tenant-a','store-a','SEP-002','SKU-B',1,50,false,'2026-09-11'),
  (16,'tenant-a','store-a','SEP-003','SKU-C',1,80,true,'2026-09-18'),
  (17,'tenant-a','store-a','SEP-004','SKU-D',1,30,false,'2026-09-25'),
  (101,'tenant-b','store-b','B-SECRET-ORDER-001','SKU-SECRET',9,8991,false,'2026-08-20');
INSERT INTO competitor_price VALUES
  (1,'tenant-a','store-a','SKU-A','CompCo',95,'2026-08-31'),
  (2,'tenant-a','store-a','SKU-B','CompCo',45,'2026-08-31'),
  (3,'tenant-a','store-a','SKU-C','CompCo',75,'2026-08-31'),
  (4,'tenant-a','store-a','SKU-D','CompCo',25,'2026-08-31');

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ecom_eval_read') THEN
    CREATE ROLE ecom_eval_read LOGIN PASSWORD 'eval_read_password'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE ecom_matrix TO ecom_eval_read;
GRANT USAGE ON SCHEMA public TO ecom_eval_read;
GRANT SELECT ON ecom_goods, ecom_order, competitor_price TO ecom_eval_read;
GRANT REFERENCES ON ecom_goods, ecom_order, competitor_price TO ecom_eval_read;

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['ecom_goods','ecom_order','competitor_price'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_store_isolation ON %I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_store_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'', true) AND store_id = current_setting(''app.store_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true) AND store_id = current_setting(''app.store_id'', true))',
      table_name
    );
  END LOOP;
END $$;
