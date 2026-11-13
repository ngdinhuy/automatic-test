#!/usr/bin/env python3
"""Biên dịch helper lab riêng bằng Android SDK/JDK; không dùng Gradle hay sửa APK Tammi."""
import os,subprocess,zipfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tammi_runner.common import load_config
cfg=load_config();sdk=Path(cfg['tools'].get('android_home',str(Path.home()/'Library/Android/sdk')))
java=Path(cfg['tools'].get('java_home','/Applications/Android Studio.app/Contents/jbr/Contents/Home'))/'bin'
build=sdk/'build-tools/35.0.0';jar=sdk/'platforms/android-35/android.jar'
if not jar.exists():jar=next(sdk.glob('platforms/android-*/android.jar'))
out=ROOT/'.runtime/audio-helper';classes=out/'classes';dex=out/'dex'
classes.mkdir(parents=True,exist_ok=True);dex.mkdir(exist_ok=True)
env={**os.environ,'JAVA_HOME':str(java.parent),'PATH':str(java)+os.pathsep+os.environ.get('PATH','')}
def run(args):subprocess.run(list(map(str,args)),env=env,check=True,capture_output=True,text=True)
run([java/'javac','--release','8','-cp',jar,'-d',classes,*sorted((ROOT/'lab-android/src').rglob('*.java'))])
run([build/'d8','--lib',jar,'--min-api','26','--output',dex,*sorted(classes.rglob('*.class'))])
unsigned=out/'unsigned.apk';run([build/'aapt','package','-f','-M',ROOT/'lab-android/AndroidManifest.xml','-I',jar,'-F',unsigned])
with zipfile.ZipFile(unsigned,'a') as package:package.write(dex/'classes.dex','classes.dex')
key=out/'lab.keystore'
if not key.exists():run([java/'keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','lab','-dname','CN=Tammi local test lab','-keyalg','RSA','-validity','3650'])
apk=out/'tammi-audio-lab.apk';run([build/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--key-pass','pass:android','--out',apk,unsigned])
print(apk)
