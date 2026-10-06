import { expect, test } from "vitest";
import { fmtQuoteTime } from "./format";

test.each([
  ["Sep 16, 2026 9:31 AM ET", "2026年09月16日 09:31 ET"],
  ["Jan 3, 2026 12:58 PM ET", "2026年01月03日 12:58 ET"],
  ["Jan 3, 2026 12:58 AM ET", "2026年01月03日 00:58 ET"],
  ["2026-09-16T23:31:00-04:00", "2026年09月16日 23:31:00 UTC-04:00"],
  ["2026-09-16T23:31:00Z", "2026年09月16日 23:31:00 UTC"],
  ["2026-09-16 09:31:41", "2026年09月16日 09:31:41（时区未标注）"],
  ["2026-09-16", "2026年09月16日"],
  ["2026-02-30T09:31:00Z", "2026-02-30T09:31:00Z（时间格式未识别）"],
  ["2026-09-16T09:31:00+99:00", "2026-09-16T09:31:00+99:00（时间格式未识别）"],
  ["unknown provider time", "unknown provider time（时间格式未识别）"],
  ["", "未标注"],
  [undefined, "未标注"],
])("preserves complete source date and timezone: %s", (raw, expected) => {
  expect(fmtQuoteTime(raw)).toBe(expected);
});
