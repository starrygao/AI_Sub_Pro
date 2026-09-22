from app.library.open_writes import writable_video_handles


def test_only_write_handles_block_media(tmp_path):
    proc=tmp_path/'proc';fd=proc/'123'/'fd';fd.mkdir(parents=True);info=proc/'123'/'fdinfo';info.mkdir()
    for number,flags,name in [('1','0100000','/media/read.mkv'),('2','0100001','/media/upload.mp4'),('3','0100002','/media/other.txt')]:
        (fd/number).symlink_to(name);(info/number).write_text('pos:\t0\nflags:\t'+flags+'\n')
    assert writable_video_handles(proc,['/media'])==['/media/upload.mp4']
