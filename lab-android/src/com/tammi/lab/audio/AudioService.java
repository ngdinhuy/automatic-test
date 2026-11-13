package com.tammi.lab.audio;

import android.app.*;
import android.content.*;
import android.media.*;
import android.os.*;
import org.json.JSONObject;
import java.io.*;

public class AudioService extends Service {
    private MediaRecorder recorder;
    private MediaPlayer player;
    private String marker="";
    private String mode="";
    private File output;
    private long started;
    private final Handler timer=new Handler(Looper.getMainLooper());

    private void state(boolean active,String error) {
        try {
            JSONObject data=new JSONObject();
            data.put("marker",marker);data.put("mode",mode);data.put("active",active);
            data.put("started_ms",started);data.put("updated_ms",System.currentTimeMillis());
            data.put("source","physical_microphone");data.put("file",output==null?"":output.getName());
            data.put("error",error);
            File file=new File(getExternalFilesDir(null),"state.json");
            try(FileOutputStream stream=new FileOutputStream(file)){stream.write(data.toString().getBytes("UTF-8"));}
        } catch(Exception ignored) {}
    }
    private void closeMedia() {
        timer.removeCallbacksAndMessages(null);
        if(recorder!=null){try{recorder.stop();}catch(Exception ignored){}recorder.release();recorder=null;}
        if(player!=null){player.release();player=null;}
    }
    @Override public int onStartCommand(Intent intent,int flags,int id) {
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("lab-audio","Tammi test audio",NotificationManager.IMPORTANCE_LOW));
        startForeground(1924,new Notification.Builder(this,"lab-audio").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Tammi Audio Lab").setContentText("Nguồn âm thanh test điều khiển bằng ADB").build());
        if(intent==null){stopSelf();return START_NOT_STICKY;}
        String action=intent.getStringExtra("action");String requested=intent.getStringExtra("marker");
        if("stop".equals(action)) {
            if(marker.equals(requested)){closeMedia();state(false,"");stopSelf();}
            else if(recorder==null && player==null)stopSelf();
            return START_NOT_STICKY;
        }
        if(recorder!=null || player!=null)return START_NOT_STICKY;
        if(requested==null || !requested.matches("[A-Za-z0-9_-]{1,100}")){stopSelf();return START_NOT_STICKY;}
        marker=requested;mode=action;started=System.currentTimeMillis();
        try {
            if("record".equals(action)) {
                output=new File(getExternalFilesDir(null),marker+".m4a");
                recorder=new MediaRecorder();recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
                recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
                recorder.setAudioSamplingRate(48000);recorder.setAudioEncodingBitRate(128000);recorder.setAudioChannels(1);
                recorder.setOutputFile(output.getAbsolutePath());recorder.prepare();recorder.start();
            } else if("play".equals(action)) {
                String filename=intent.getStringExtra("file");
                if(filename==null || !filename.matches("[A-Za-z0-9_.-]+"))throw new IOException("Tên fixture không hợp lệ");
                player=new MediaPlayer();player.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build());
                player.setDataSource(new File(getExternalFilesDir(null),filename).getAbsolutePath());
                player.setLooping(true);player.prepare();player.start();
            } else throw new IOException("Action không hợp lệ");
            state(true,"");int duration=Math.max(1000,Math.min(30000,intent.getIntExtra("duration_ms",10000)));
            timer.postDelayed(()->{closeMedia();state(false,"");stopSelf();},duration);
        } catch(Exception error){closeMedia();state(false,error.toString());stopSelf();}
        return START_NOT_STICKY;
    }
    @Override public void onDestroy(){closeMedia();state(false,"");super.onDestroy();}
    @Override public IBinder onBind(Intent i){return null;}
}
