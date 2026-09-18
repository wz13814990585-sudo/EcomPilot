-- Rename the historical internal-bus table without losing deployed trace data.
DO $$
BEGIN
  IF to_regclass('public.mcp_message_log') IS NOT NULL
     AND to_regclass('public.agent_message_log') IS NULL THEN
    ALTER TABLE mcp_message_log RENAME TO agent_message_log;
  END IF;
END $$;
