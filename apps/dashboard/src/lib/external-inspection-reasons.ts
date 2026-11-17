/**
 * 파일 검사(external_geotiff_inspector)가 REJECTED 로 돌려주는 사유 코드를 사람 말로 옮긴다.
 * 코드는 검사기의 닫힌 목록이다. 모르는 코드는 null 을 돌려 화면이 일반 문구로 접게 한다.
 * 올리기 전 점검(geotiff-preflight)과 같은 규칙을 가리키므로, 안내 문구가 서로 어긋나지 않게 함께 고친다.
 */

export type InspectionReasonText = {
  /** 무슨 일이 있었는지. */
  text: string;
  /** 사용자가 다시 내보낼 때 무엇을 바꿔야 하는지. */
  fix: string;
};

const REASONS: Record<string, InspectionReasonText> = {
  MALFORMED_TIFF: {
    text: "파일을 TIFF로 읽지 못했거나 지원하는 구조가 아닙니다. 손상일 수도 있고, 16비트 정사영상이나 정수 DSM처럼 허용 범위 밖의 자료일 수도 있습니다.",
    fix: "정사영상은 8비트 RGB(또는 RGBA), DSM은 Float32 한 밴드로 다시 내보내 보세요. 같은 결과이면 파일이 손상되지 않았는지 확인하세요.",
  },
  UNSUPPORTED_RASTER: {
    text: "압축 방식, 색 방식, 밴드 구성 중 지원하지 않는 설정이 있습니다. 예를 들어 알파가 있는 JPEG 정사영상, NoData 가 지정된 정사영상, 배율이 지정된 DSM이 그렇습니다.",
    fix: "LZW나 Deflate 압축으로 다시 내보내세요. 정사영상은 NoData 지정 없이, 투명도는 0 또는 255 두 값으로 내보내세요.",
  },
  AMBIGUOUS_GEOREFERENCE: {
    text: "좌표계를 하나로 확정할 수 없습니다. 좌표 정보가 없거나, EPSG 번호가 없거나, DSM이 위·경도 또는 미터가 아닌 단위이거나, 수직 기준이 EPSG가 아닌 경우입니다.",
    fix: "EPSG 번호가 있는 투영 좌표계(예: UTM, 중부원점)로 내보내세요. 별도 좌표 파일(.tfw, .prj)은 읽지 않습니다.",
  },
  UNMASKED_NONFINITE_SAMPLE: {
    text: "DSM에 NoData 로 표시되지 않은 NaN 또는 무한대 값이 있습니다.",
    fix: "NoData 값을 지정하거나 마스크를 넣어 다시 내보내세요.",
  },
  UNSAFE_EXTERNAL_REFERENCE: {
    text: "다른 파일을 가리키는 파일(.ovr, .msk, VRT 등)은 받지 않습니다.",
    fix: "오버뷰와 마스크를 파일 안에 포함한 하나의 GeoTIFF로 내보내세요.",
  },
  RESOURCE_LIMIT_EXCEEDED: {
    text: "파일이 검사 한도(크기 또는 픽셀 수)를 넘었습니다.",
    fix: "내보내기에서 작업구역만 잘라 내거나 해상도를 낮춰 다시 내보내세요.",
  },
};

export function describeInspectionReason(code: string): InspectionReasonText | null {
  return Object.prototype.hasOwnProperty.call(REASONS, code) ? REASONS[code] : null;
}
