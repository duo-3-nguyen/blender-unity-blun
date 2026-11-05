



- material slot:
    - blender: lưu theo từng mặt
    - unity: lưu dưới dạng submesh. để tối ưu cho tốc độ render, unity yêu cầu các mặt có cùng material sẽ sắp xếp liền kề nhau. Lệnh gán submesh sẽ là gán đoạn (start, length)


# .blun

Đã chuyển đổi sang hệ tọa độ của unity, dữ liệu được lưu đúng theo unity convention. attribute nào không có thì skip.

```jsonc
{
    "format": "blun",
    "version": 1,

    "meshes": [
        {
            "name": "Suzanne",

            "attributes": {
                "position": { "start": 0, "count": 0 }, // float32 × 3
                "normal": { "start": 0, "count": 0 }, // float32 × 3
                "tangent": { "start": 0, "count": 0 }, // float32 × 4
                "uv0": { "start": 0, "count": 0 }, // float32 × 2
                "uv1": { "start": 0, "count": 0 }, // float32 × 2, uv có từ 0 đến 7
                "indices": { "format": "uint16", "start": 0, "count": 0 }, // uint16 hoặc uint32, tùy xem mesh có nhiều vertex không?

                "bonesPerVertex": { "start": 0, "count": 0 }, // uint8
                "weights": { "start": 0, "count": 0 }, // same as BoneWeight1 struct: int32 + float32
            },

            "submeshes": [
                {
                    "indexStart": 0,
                    "indexCount": 5895,
                    "materialIndex": 0
                }
            ],

            "data": "BASE64_DATA"
        }
    ],

    "skeletons": [

    ],

    "animations": [

    ]   
}

{


}
```