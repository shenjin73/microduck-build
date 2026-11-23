"""Fill only the three obsolete eye slots; deliver all four head parts."""
from pathlib import Path
import runpy, json, re, zipfile, io
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as md

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
V5=ROOT/'眼睛防护螺丝固定_v5'
V4=ROOT/'防脱螺丝固定_v4'
shared=runpy.run_path(str(ROOT/'防脱螺丝固定_v1'/'build_variant.py'))
solid,mesh_of,box,mesh_xml=[shared[k]for k in ['to_manifold','to_mesh','box','mesh_xml']]
CORE='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
NS={'m':CORE}
FILES={
 'face':'鸭脸_瑞莎IMX219_旧槽填实_v6.stl',
 'eye':'眼睛_10p5mm防护螺丝固定_v6.stl',
 'bottom':'头部集成板_M2防脱_v6.stl',
 'cover':'头盖_原样.stl',
}
HEAD='头部部件_眼睛防护_旧槽填实_v6.3mf'
OFFSET=np.array([0.,-48.850000381470,21.513240456581])


def main():
    original=trimesh.load(V5/'鸭脸_瑞莎IMX219_眼睛螺丝固定_v5.stl',force='mesh')
    section=original.section(plane_origin=[0,-55.49,0],plane_normal=[0,1,0])
    slots=[]
    for a in section.discrete:
        q=a[:,[0,2]]
        radial=np.linalg.norm(q-[0,20],axis=1)
        if radial.min()>8.1 and radial.max()<9.8 and np.ptp(q,axis=0).max()<3.6:
            slots.append(q)
    assert len(slots)==3,len(slots)
    fillers=md.Manifold()
    for q in slots:
        # Grow laterally0.04mm to fuse into walls; front/rear stay flush.
        signed_area=np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))
        if signed_area<0:
            q=q[::-1]
        cross=md.CrossSection([q.tolist()]).offset(.04)
        assert cross.area()>0
        fillers+=cross.extrude(1.3).rotate([90,0,0]).translate([0,-54.2,0])
    before=solid(original)
    after=before+fillers
    face=mesh_of(after)
    assert abs((before-after).volume())<.001,'Unexpected removed material'
    # Protect camera opening, new screw holes and all mounting posts.
    protection=md.Manifold.cylinder(3,7.3,circular_segments=144).rotate([-90,0,0]).translate([0,-55.7,20])
    eye_centres=[[0.,31.5],[-9.9592921435,14.25],[9.9592921435,14.25]]
    for x,z in eye_centres:
        protection+=md.Manifold.cylinder(3,1.3,circular_segments=72).rotate([-90,0,0]).translate([x,-55.7,z])
    for x,z,r,yend in [(x,z,2.3,-48.19)for x in [-14,14]for z in [6,34]]+[(x,z,3.05,-41.19)for x in [-28.92,28.92]for z in [8.565,31.435]]:
        protection+=box([x-r,-54.21,z-r],[x+r,yend,z+r])
    protected_added=max(0.,((after-before)^protection).volume())
    assert protected_added<.001
    # Actual slot centre solids now exist all the way through the face thickness.
    for q in slots:
        centre=q.mean(0)
        probe=box([centre[0]-.05,-55.45,centre[1]-.05],[centre[0]+.05,-54.25,centre[1]+.05])
        assert abs((after^probe).volume()-probe.volume())<1e-5
    face.export(HERE/FILES['face'])
    # These three parts are unchanged. Copy binary STL, not a re-tessellation.
    for source,key in [(V5/'眼睛_10p5mm防护螺丝固定_v5.stl','eye'),
                       (V4/'头部集成板_M2防脱_v4.stl','bottom'),
                       (V4/'头盖_原样.stl','cover')]:
        (HERE/FILES[key]).write_bytes(source.read_bytes())
    with zipfile.ZipFile(V5/'头部部件_眼睛防护_v5.3mf')as z:raw={n:z.read(n)for n in z.namelist()}
    local=face.copy();local.apply_translation(-OFFSET)
    raw['3D/Objects/object_26.model']=mesh_xml(raw['3D/Objects/object_26.model'],local)
    text=raw['3D/3dmodel.model'].decode()
    text=re.sub(r'<metadata name="Title">.*?</metadata>','<metadata name="Title">Head eye protection v6 obsolete slots filled</metadata>',text)
    raw['3D/3dmodel.model']=text.encode()
    settings=ET.fromstring(raw['Metadata/model_settings.config'])
    for obj in settings.findall('object'):
        key={'2':'bottom','4':'cover','6':'face','10':'eye'}.get(obj.get('id'))
        if not key:continue
        for meta in obj.findall('.//metadata'):
            if meta.get('key')in ['name','source_file']:meta.set('value',FILES[key])
            if key=='face'and 'face_count'in meta.attrib:meta.set('face_count',str(len(face.faces)))
        if key=='face':
            for stat in obj.findall('.//mesh_stat'):stat.set('face_count',str(len(face.faces)))
    raw['Metadata/model_settings.config']=ET.tostring(settings,encoding='utf-8',xml_declaration=True)
    # Regenerate the active4-part plate thumbnail.
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
        tr=np.array([float(a)for a in item.get('transform').split()]).reshape(4,3)
        v=v@tr[:3]+tr[3]
        ax.add_collection3d(Poly3DCollection(v[f],facecolor='#ddd',edgecolor='#777',linewidth=.025))
    ax.set_xlim(0,256);ax.set_ylim(0,256);ax.set_zlim(0,50);ax.set_box_aspect([256,256,50]);ax.view_init(55,-65);ax.set_axis_off()
    buf=io.BytesIO();fig.savefig(buf,format='png',dpi=120,bbox_inches='tight',pad_inches=0);plt.close(fig)
    image=Image.open(io.BytesIO(buf.getvalue())).convert('RGBA')
    for name in ['Metadata/plate_1.png','Metadata/plate_1_small.png','Metadata/plate_no_light_1.png']:
        size=Image.open(io.BytesIO(raw[name])).size;out=io.BytesIO();image.resize(size,Image.Resampling.LANCZOS).save(out,format='PNG');raw[name]=out.getvalue()
    with zipfile.ZipFile(HERE/HEAD,'w',zipfile.ZIP_DEFLATED)as z:
        for n,b in raw.items():z.writestr(n,b)
    # Front view exposes any accidental changes to nearby holes.
    fig,ax=plt.subplots(figsize=(10,6))
    sec=face.section(plane_origin=[0,-55.49,0],plane_normal=[0,1,0])
    for a in sec.discrete:ax.plot(a[:,0],a[:,2],color='#527692',lw=1)
    ax.set_aspect('equal');ax.set_xlabel('X mm');ax.set_ylabel('Z mm');ax.set_title('v6 face:3 old arc slots filled;3 screw holes and lens aperture preserved');ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(HERE/'旧槽填实正面预览.png',dpi=150);plt.close(fig)
    report={'version':'v6 / obsolete eye slots filled','filled_slots':3,
            'slot_bounds_XZ':[[q.min(0).tolist(),q.max(0).tolist()]for q in slots],
            'added_volume_mm3':max(0.,(after-before).volume()),'removed_volume_mm3':max(0.,(before-after).volume()),
            'protected_camera_holes_and_mounts_added_volume_mm3':protected_added,
            'face_watertight':bool(face.is_watertight),'face_winding_consistent':bool(face.is_winding_consistent),
            'complete_STL_parts':FILES,'unchanged_parts':['eye','bottom','cover'],
            'camera_pillar_mm':6,'zero_pillar_mm':13,'eye_height_mm':10.5,
            'inherited_limitations':'v5 physical-fit,full camera/ZERO/HAT components,and impact testing remain unverified'}
    (HERE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('OUTPUT',HERE/HEAD)


if __name__=='__main__':main()
