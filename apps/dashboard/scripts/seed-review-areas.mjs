#!/usr/bin/env node
/**
 * 검토 스택(`run-data-state-stack.mjs`)의 현장에 실제 크기의 작업구역을 더 등록한다.
 *
 * 합성 픽스처의 구역은 몇 미터짜리라 지도 배경이 보이지 않고 구역이 하나뿐이어서, 영역 지도·목록·대체 흐름을
 * 눈으로 판단하기 어렵다. 이 스크립트는 같은 Core에 구역 3개(하나는 다른 구역을 대체해 이전 구역이 보관됨)를
 * 더한다. 합성 위치이며 실제 현장·정확도·고객 수락 증거가 아니다. Core는 메모리 저장이라 스택을 다시 띄우면
 * 사라지니, 다시 띄운 뒤 이 스크립트를 한 번 더 실행한다.
 *
 * 사용: node scripts/seed-review-areas.mjs [--info-file ../../.dev-data/data-states/info.json]
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const appDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const flag = process.argv.indexOf("--info-file");
const infoFile = resolve(appDirectory, flag === -1 ? "../../.dev-data/data-states/info.json" : process.argv[flag + 1]);
const info = JSON.parse(readFileSync(infoFile, "utf8"));
const headers = { "content-type": "application/json", authorization: `Bearer ${info.operatorToken}` };
const base = `${info.coreOrigin}/v1/sites/${encodeURIComponent(info.siteId)}/work-areas`;

// 서울 도심 한 곳을 기준으로 한 합성 직사각형(약 240m × 180m).
const rect = (lon, lat, w = 0.0028, h = 0.0016) => ({
  type: "Polygon",
  coordinates: [[[lon, lat], [lon + w, lat], [lon + w, lat + h], [lon, lat + h], [lon, lat]]],
});

async function register(body) {
  const response = await fetch(base, { method: "POST", headers, body: JSON.stringify({ crs: "EPSG:4326", supersedes: null, ...body }) });
  const text = await response.text();
  if (!response.ok) throw new Error(`${body.name}: ${response.status} ${text.slice(0, 200)}`);
  return JSON.parse(text);
}

const north = await register({ name: "1구역 북측", polygon: rect(126.9780, 37.5700) });
const fill = await register({ name: "2구역 성토부", polygon: rect(126.9815, 37.5683, 0.0022, 0.0014) });
// 같은 이름·다른 범위로 대체 — 이전 구역은 Core가 보관한다.
const north2 = await register({ name: "1구역 북측", polygon: rect(126.9778, 37.5702, 0.0032, 0.0018), supersedes: north.workAreaId ?? north.workArea?.workAreaId });
console.log("등록:", [north, fill, north2].map((area) => area.workAreaId ?? area.workArea?.workAreaId).join(", "));
