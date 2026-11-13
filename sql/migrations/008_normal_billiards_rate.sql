-- Change only the current normal billiards category rate.
-- Session hourly_rate_applied and total_cost history are not recalculated.
UPDATE unit_categories
SET hourly_rate = 100.00
WHERE name = 'Normal Billiards'
  AND unit_type = 'BILLIARDS'
  AND hourly_rate <> 100.00;
