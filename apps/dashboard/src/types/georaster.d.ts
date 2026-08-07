/**
 * `georaster` 는 타입 정의를 내지 않는다(package.json 에 `types` 필드 없음).
 * 반환 형태(`GeoRaster`)는 `georaster-layer-for-leaflet` 이 이미 선언한
 * 것과 같으므로 그걸 재사용하고, 여기서는 진입점 함수 하나만 선언한다.
 */
declare module "georaster" {
  import type { GeoRaster } from "georaster-layer-for-leaflet";

  export default function parseGeoraster(input: ArrayBuffer | Blob): Promise<GeoRaster>;
}
