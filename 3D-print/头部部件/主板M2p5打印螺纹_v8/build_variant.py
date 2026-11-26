"""v8: M2.5x0.45 printed internal threads in the four ZERO mounting posts.
No nuts/inserts. Prints are prototypes until tested with the user's screw.
Only v7 inputs are needed; no earlier intermediate version dependencies.
"""
from pathlib import Path
import runpy,json,re,zipfile,io
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as md

HERE=Path(__file__).resolve().parent
V7=HERE.parent/'摄像头右移2mm_v7'
shared=runpy.run_path(str(V7/'build_variant.py'))
solid,mesh_of,box,replace_mesh=[shared[k]for k in ['solid','mesh_of','box','replace_mesh']]
CORE='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
NS={'m':CORE}
OFFSET=np.array([0.,-48.850000381470,21.513240456581])
FILES={'face':'鸭脸_主板M2p5打印螺纹_v8.stl',
       'eye':'眼睛_10p5mm防护螺丝固定_v8.stl',
       'bottom':'头部集成板_M2防脱_v8.stl','cover':'头盖_原样.stl'}
HEAD='头部部件_主板M2p5打印螺纹_v8.3mf'
PITCH=.45
MINOR_DIAMETER=2.18
MAJOR_DIAMETER=2.66
DEPTH=6.4
CENTRES=[(x,z)for x in [-28.92,28.92]for z in [8.565,31.435]]


def helical_groove():
    # 60-degree trapezoidal thread groove; overlaps the cylindrical minor bore.
    # Radial clearance is deliberately added for FDM, not a precision metal thread.
    r_minor=MINOR_DIAMETER/2
    r0=r_minor-.05
    r1=MAJOR_DIAMETER/2
    root_width=PITCH/8
    inner_width=root_width+2*(r1-r0)*np.tan(np.deg2rad(30))
    assert inner_width<PITCH
    profile=[(r0,-inner_width/2),(r1,-root_width/2),(r1,root_width/2),(r0,inner_width/2)]
    start,end=-.1,6.1
    n=int(np.ceil((end-start)/PITCH*144))+1
    theta=np.linspace(0,(end-start)/PITCH*2*np.pi,n)
    verts=[]
    # Positive mathematical rotation with+Z advance is a RH helix.
    # Looking INTO the mouth along+Z, this is a clockwise advance.
    for t in theta:
        z=start+t/(2*np.pi)*PITCH
        for r,dz in profile:verts.append([r*np.cos(t),r*np.sin(t),z+dz])
    faces=[]
    for i in range(n-1):
        for k in range(4):
            a=4*i+k;b=4*i+(k+1)%4;c=4*(i+1)+(k+1)%4;d=4*(i+1)+k
            faces.extend([[a,b,c],[a,c,d]])
    faces.extend([[0,2,1],[0,3,2]])
    j=4*(n-1);faces.extend([[j,j+1,j+2],[j,j+2,j+3]])
    mesh=trimesh.Trimesh(np.array(verts),np.array(faces),process=True)
    mesh.fix_normals()
    assert mesh.is_watertight and mesh.is_winding_consistent
    return solid(mesh)


def main():
    original=trimesh.load(V7/'鸭脸_瑞莎IMX219_摄像头右移2mm_v7.stl',force='mesh')
    old=solid(original);face=old
    groove=helical_groove()
    pilot=md.Manifold.cylinder(DEPTH+.1,MINOR_DIAMETER/2,circular_segments=144).translate([0,0,-.1])
    thread_cutter=groove+pilot
    changed_regions=md.Manifold()
    for x,z in CENTRES:
        # Depth axis+Z maps to-Y from the existing post mouthY=-41.2.
        cutter=thread_cutter.rotate([90,0,0]).translate([x,-41.2,z])
        face-=cutter
        changed_regions+=box([x-1.5,-47.7,z-1.5],[x+1.5,-41.19,z+1.5])
    modified=mesh_of(face)
    removed=max(0.,(old-face).volume())
    added=max(0.,(face-old).volume())
    outside=max(0.,((old-face)-changed_regions).volume())
    assert added<.001 and outside<.001
    # A coupon copies the same groove and original1mm entrance bore.
    coupon=md.Manifold.cylinder(8,3,circular_segments=144)+box([-5,-5,0],[5,5,2])
    coupon-=thread_cutter.rotate([180,0,0]).translate([0,0,8])
    coupon-=md.Manifold.cylinder(1.05,1.35,circular_segments=144).translate([0,0,7])
    coupon_mesh=mesh_of(coupon)
    coupon_mesh.export(HERE/'M2p5螺纹试样_先打印.stl')
    modified.export(HERE/FILES['face'])
    for src,key in [(V7/'眼睛_10p5mm防护螺丝固定_v7.stl','eye'),(V7/'头部集成板_M2防脱_v7.stl','bottom'),(V7/'头盖_原样.stl','cover')]:
        (HERE/FILES[key]).write_bytes(src.read_bytes())
    with zipfile.ZipFile(V7/'头部部件_摄像头右移2mm_v7.3mf')as z:raw={n:z.read(n)for n in z.namelist()}
    local=modified.copy();local.apply_translation(-OFFSET)
    raw['3D/Objects/object_26.model']=replace_mesh(raw['3D/Objects/object_26.model'],local)
    text=re.sub(r'<metadata name="Title">.*?</metadata>','<metadata name="Title">Head v8 M2.5x0.45 printed mainboard threads prototype</metadata>',raw['3D/3dmodel.model'].decode())
    raw['3D/3dmodel.model']=text.encode()
    settings=ET.fromstring(raw['Metadata/model_settings.config'])
    for obj in settings.findall('object'):
        key={'2':'bottom','4':'cover','6':'face','10':'eye'}.get(obj.get('id'))
        if not key:continue
        for meta in obj.findall('.//metadata'):
            if meta.get('key')in ['name','source_file']:meta.set('value',FILES[key])
            if key=='face'and 'face_count'in meta.attrib:meta.set('face_count',str(len(modified.faces)))
        if key=='face':
            for stat in obj.findall('.//mesh_stat'):stat.set('face_count',str(len(modified.faces)))
    raw['Metadata/model_settings.config']=ET.tostring(settings,encoding='utf-8',xml_declaration=True)
    cfg=json.loads(raw['Metadata/project_settings.config']);cfg['layer_height']='0.12'
    raw['Metadata/project_settings.config']=json.dumps(cfg,ensure_ascii=False,indent=2).encode()
    # All parts keep originalprint transforms. Refresh modelthumbnail below.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from PIL import Image
    fig=plt.figure(figsize=(6,6));ax=fig.add_subplot(111,projection='3d')
    paths={'2':'3D/Objects/object_2.model','4':'3D/Objects/object_358.model','6':'3D/Objects/object_26.model','10':'3D/Objects/object_eye_v5.model'}
    for item in ET.fromstring(raw['3D/3dmodel.model']).findall('m:build/m:item',NS):
        if item.get('objectid')not in paths:continue
        rr=ET.fromstring(raw[paths[item.get('objectid')]])
        v=np.array([[float(t.get(c))for c in 'xyz']for t in rr.findall('.//m:vertex',NS)])
        f=np.array([[int(t.get(c))for c in ['v1','v2','v3']]for t in rr.findall('.//m:triangle',NS)])
        tr=np.array([float(a)for a in item.get('transform').split()]).reshape(4,3);v=v@tr[:3]+tr[3]
        ax.add_collection3d(Poly3DCollection(v[f],facecolor='#ddd',edgecolor='#777',linewidth=.02))
    ax.set_xlim(0,256);ax.set_ylim(0,256);ax.set_zlim(0,50);ax.set_box_aspect([256,256,50]);ax.view_init(55,-65);ax.set_axis_off()
    buf=io.BytesIO();fig.savefig(buf,format='png',dpi=120,bbox_inches='tight',pad_inches=0);plt.close(fig)
    image=Image.open(io.BytesIO(buf.getvalue())).convert('RGBA')
    for name in ['Metadata/plate_1.png','Metadata/plate_1_small.png','Metadata/plate_no_light_1.png']:
        size=Image.open(io.BytesIO(raw[name])).size;out=io.BytesIO();image.resize(size,Image.Resampling.LANCZOS).save(out,format='PNG');raw[name]=out.getvalue()
    with zipfile.ZipFile(HERE/HEAD,'w',zipfile.ZIP_DEFLATED)as z:
        for n,b in raw.items():z.writestr(n,b)
    # Small standaloneBambu project with the same0.12mm layer preset.
    coupon_raw=dict(raw)
    ET.register_namespace('p','http://schemas.microsoft.com/3dmanufacturing/production/2015/06')
    root=ET.fromstring(coupon_raw['3D/3dmodel.model'])
    resources=root.find('m:resources',NS)
    for obj in list(resources):
        if obj.get('id')!='10':resources.remove(obj)
    build=root.find('m:build',NS)
    for item in list(build):
        if item.get('objectid')!='10':build.remove(item)
        else:item.set('transform','1 0 0 0 1 0 0 0 1 128 128 0')
    for meta in root.findall('m:metadata',NS):
        if meta.get('name')=='Title':meta.text='M2.5 printed thread test coupon'
    coupon_raw['3D/3dmodel.model']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    coupon_raw['3D/Objects/object_eye_v5.model']=replace_mesh(coupon_raw['3D/Objects/object_eye_v5.model'],coupon_mesh)
    for name in list(coupon_raw):
        if name.startswith('3D/Objects/')and name!='3D/Objects/object_eye_v5.model':del coupon_raw[name]
    relns='{http://schemas.openxmlformats.org/package/2006/relationships}'
    relroot=ET.fromstring(coupon_raw['3D/_rels/3dmodel.model.rels'])
    for rel in list(relroot):
        if rel.get('Target')!='/3D/Objects/object_eye_v5.model':relroot.remove(rel)
    coupon_raw['3D/_rels/3dmodel.model.rels']=ET.tostring(relroot,encoding='utf-8',xml_declaration=True)
    settings=ET.fromstring(coupon_raw['Metadata/model_settings.config'])
    for obj in list(settings.findall('object')):
        if obj.get('id')!='10':settings.remove(obj)
        else:
            for meta in obj.findall('.//metadata'):
                if meta.get('key')in ['name','source_file']:meta.set('value','M2p5螺纹试样_先打印.stl')
                if 'face_count'in meta.attrib:meta.set('face_count',str(len(coupon_mesh.faces)))
            for stat in obj.findall('.//mesh_stat'):stat.set('face_count',str(len(coupon_mesh.faces)))
    plate=settings.find('plate')
    for instance in list(plate.findall('model_instance')):
        if instance.find("metadata[@key='object_id']").get('value')!='10':plate.remove(instance)
    for node in list(settings.findall('assemble')):settings.remove(node)
    coupon_raw['Metadata/model_settings.config']=ET.tostring(settings,encoding='utf-8',xml_declaration=True)
    fig=plt.figure(figsize=(6,6));ax=fig.add_subplot(111,projection='3d')
    ax.add_collection3d(Poly3DCollection(coupon_mesh.triangles,facecolor='#ddd',edgecolor='#777',linewidth=.03))
    ax.set_xlim(-6,6);ax.set_ylim(-6,6);ax.set_zlim(0,9);ax.set_box_aspect([12,12,9]);ax.view_init(55,-65);ax.set_axis_off()
    buf=io.BytesIO();fig.savefig(buf,format='png',dpi=120,bbox_inches='tight',pad_inches=0);plt.close(fig)
    image=Image.open(io.BytesIO(buf.getvalue())).convert('RGBA')
    for name in ['Metadata/plate_1.png','Metadata/plate_1_small.png','Metadata/plate_no_light_1.png']:
        size=Image.open(io.BytesIO(coupon_raw[name])).size;out=io.BytesIO();image.resize(size,Image.Resampling.LANCZOS).save(out,format='PNG');coupon_raw[name]=out.getvalue()
    with zipfile.ZipFile(HERE/'M2p5螺纹试样_先打印.3mf','w',zipfile.ZIP_DEFLATED)as z:
        for n,b in coupon_raw.items():z.writestr(n,b)
    # Thread section using actual coupon geometry, not a schematic.
    sec=coupon_mesh.section(plane_origin=[0,0,0],plane_normal=[0,1,0])
    fig,ax=plt.subplots(figsize=(7,6))
    for line in sec.discrete:ax.plot(line[:,0],8-line[:,2],color='#527692',lw=.8)
    ax.set_xlim(-2,2);ax.set_ylim(6.5,-.2);ax.set_aspect('equal');ax.set_xlabel('Radial section mm');ax.set_ylabel('Depth from post mouth mm');ax.set_title('M2.5x0.45 printed internal thread /0.12mm layers');ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(HERE/'主板孔打印螺纹剖面.png',dpi=150);plt.close(fig)
    report={'version':'v8 printed thread prototype/no inserts',
            'screw':'M2.5x0.45 standard right-hand machine screw,user photo6mm under-head length',
            'pitch_mm':PITCH,'FDM_minor_diameter_mm':MINOR_DIAMETER,'FDM_major_diameter_mm':MAJOR_DIAMETER,
            'bore_depth_mm':DEPTH,'original_entrance_diameter_mm':2.7,
            'recommended_layer_height_mm':.12,'post_centres_XZ':CENTRES,'post_height_mm':13,
            'removed_volume_mm3':removed,'added_volume_mm3':added,'changes_outside_four_bore_regions_mm3':outside,
            'watertight':bool(modified.is_watertight),'winding_consistent':bool(modified.is_winding_consistent),
            'thread_handedness':'RH:clockwise rotation viewed into mouth increases depth',
            'coupon':'M2p5螺纹试样_先打印.stl',
            'unchanged_parts':['eye','bottom','cover'],
            'limitations':['FDM small threads not physically test-fit;coupon must pass before printing wholeface',
                           'Clearance is a prototype allowance,not a machined ISO tolerance class',
                           'Inherited v7 ToF fastener overlap and0.4mm PCB/ear margin remain unverified']}
    (HERE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('OUTPUT',HERE/HEAD)


if __name__=='__main__':main()
