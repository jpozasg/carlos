-- 039_fault_component_code.sql (#221 phase 3): a controlled component code per fault; `component` stays readable English.
-- No CHECK: the vocabulary lives in config.FAULT_COMPONENTS and grows without a table rebuild; the API enforces it.
ALTER TABLE faults ADD COLUMN component_code TEXT;
CREATE INDEX faults_component_code ON faults (part, component_code);
