export type Branch = {
  id: number;
  name: string;
  code: string;
  timezone: string;
  address: string;
  working_days: string;
  grace_minutes: number | null;
  default_shift_id: number | null;
  work_start: string;
  work_end: string;
};

export type Shift = {
  id: number;
  name: string;
  start_time: string;
  end_time: string;
  grace_minutes: number | null;
  branch_id: number | null;
};
