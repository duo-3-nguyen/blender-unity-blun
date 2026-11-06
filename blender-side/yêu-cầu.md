



- material slot:
    - blender: lưu theo từng mặt
    - unity: lưu dưới dạng submesh. để tối ưu cho tốc độ render, unity yêu cầu các mặt có cùng material sẽ sắp xếp liền kề nhau. Lệnh gán submesh sẽ là gán đoạn (start, length)

Nhớ check xem thiết bị có hỗ trợ không?

```cs
bool supported = SystemInfo.SupportsVertexAttributeFormat(VertexAttributeFormat.Float16, 2);
```

Nhớ check các flag nhé

Không hỗ trợ shape key có normal, tangent

```cs
var mesh = new Mesh();


// vertex
var vertexCount = 10;
mesh.SetVertexBufferParams(
    vertexCount, 
    new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
    new VertexAttributeDescriptor(VertexAttribute.Normal, VertexAttributeFormat.Float16, 2),
    new VertexAttributeDescriptor(VertexAttribute.Tangent, VertexAttributeFormat.UNorm8, 4),
);
mesh.SetVertexBufferData(data, 0, 0, vertexCount);


// face
mesh.SetIndexBufferParams(data2.Length, IndexFormat.UInt16);
mesh.SetIndexBufferData(data2, 0, 0, data2.Length);


// submesh
mesh.subMeshCount = 1;
mesh.SetSubMeshes(
    new[] {
        new SubMeshDescriptor(0, data2.Length, MeshTopology.Triangles)
    },
    0,
    0
);

// bone
mesh.SetBoneWeights(bonesPerVertexArray, weightsArray);

// bindpose
mesh.bindposes = bindPoses;

// blendshape
mesh.AddBlendShapeFrame("Smile", 100f, deltaVertices, deltaNormals, deltaTangents);
mesh.AddBlendShapeFrame("Tung tung tung", 100f, deltaVertices2, null, null);

// reacalulate
mesh.RecalculateBounds();

// optimize
mesh.Opzitmize();
```

# .blun

Đã chuyển đổi sang hệ tọa độ của unity, dữ liệu được lưu đúng theo unity convention. attribute nào không có thì skip.

```jsonc
{
    "format": "blun",
    "version": 1,

    "meshes": [
        {
            "name": "Suzanne",


            "vertex_layout": { // xem tại https://docs.unity.com/en-us/engine/6000.3/script-reference/unityengine/rendering/vertexattribute
                { "attribute": "Position", "format": "Float32", "dimension": 3},
                { "attribute": "Normal", "format": "Float32", "dimension": 3},
                { "attribute": "Tangent", "format": "UNorm16", "dimension": 4},
                { "attribute": "Color", "format": "UNorm8", "dimension": 4},
                { "attribute": "TexCoord0", "format": "UNorm16", "dimension": 2},
                { "attribute": "TexCoord1", "format": "UNorm16", "dimension": 2}, // tùy xem có bao nhiêu uv (0 -> 7)
            },
            "vertex_data": "BASE64_DATA",

            "index_format": "UInt16", // UInt16 hoặc UInt32, tùy xem mesh có nhiều vertex không? xem thêm ở Unity enum IndexFormat
            "indices": "BASE64_DATA", // 3 giá trị tạo 1 mặt, đã sắp xếp để phù hợp với submesh, 

            "bonesPerVertex": "BASE64_DATA", // uint8
            "weights": "BASE64_DATA", // same as BoneWeight1 struct: int32 + float32
            "bindposes": "BASE64_DATA",

            "submeshes": [
                {
                    "indexStart": 0,
                    "indexCount": 5895,
                    "materialIndex": 0
                }
            ],

            "blendshapes": [
                "name": "Smile",

            ]
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