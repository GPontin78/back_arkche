/* Executar no banco separado de LOG. Os registros antigos ficam com IP nulo. */
SET BAIL ON;
SET AUTODDL OFF;
ALTER TABLE LOG ADD IP VARCHAR(45);
COMMIT;
