from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..deps import get_sources, get_video_jobs
from ..schemas import VideoJobInfo, VideoRequest
from ..services import find_source_for_account
from ..video import VideoJobManager

router = APIRouter(tags=["video"])


@router.post("/video", response_model=VideoJobInfo, status_code=202)
def start_video(req: VideoRequest, jobs: VideoJobManager = Depends(get_video_jobs),
                sources: dict = Depends(get_sources)):
    find_source_for_account(sources, req.account_id)  # 404 before queuing
    return jobs.submit(req.model_dump(exclude={"sample_paths"})).to_dict()


@router.get("/video/jobs/{job_id}", response_model=VideoJobInfo)
def video_job(job_id: str, jobs: VideoJobManager = Depends(get_video_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown video job.")
    return job.to_dict()


@router.get("/video/{video_id}")
def download_video(video_id: str, download: bool = False, jobs: VideoJobManager = Depends(get_video_jobs)):
    clip = jobs.video(video_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="This video has expired. Create it again.")
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{clip.file_name}"', "Accept-Ranges": "bytes"}
    return Response(content=clip.data, media_type="video/mp4", headers=headers)
