import os
import json
import pathlib
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import threading
from queue import Queue
from datetime import datetime

class FFmpegApp:
    def __init__(self, root):
        self.root = root
        self.root.title("视频处理工具")
        self.root.minsize(500, 400)
        self.folder_path = tk.StringVar()
        self.burn_mode = tk.StringVar(value="balanced")
        self.split_length = tk.StringVar(value="6")
        self.subtitle_delay = tk.DoubleVar(value=0.0) 
        self.progress = tk.DoubleVar()
        self.log_queue = Queue()
        self.process_running = False
        if not self.check_ffmpeg():
            messagebox.showerror("错误", "未检测到FFmpeg，请先安装并添加到系统PATH")
            root.after(100, root.destroy)
            return
        self.setup_ui()
        self.update_log()

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        folder_frame = ttk.LabelFrame(main_frame, text="源文件夹", padding="10")
        folder_frame.pack(fill=tk.X, pady=5)
        ttk.Label(folder_frame, text="路径:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(folder_frame, textvariable=self.folder_path, width=40).grid(row=0, column=1, sticky=tk.EW)
        ttk.Button(folder_frame, text="选择文件夹", command=self.choose_folder).grid(row=0, column=2, padx=5)
        mode_frame = ttk.LabelFrame(main_frame, text="烧录模式", padding="10")
        mode_frame.pack(fill=tk.X, pady=5)
        modes = [
            ("无损 (高质量，大文件)", "lossless"),
            ("均衡 (推荐)", "balanced"),
            ("极速 (低质量，速度快)", "fast")
        ]
        for i, (text, mode) in enumerate(modes):
            ttk.Radiobutton(mode_frame, text=text, variable=self.burn_mode,
                            value=mode, command=self.check_ready).grid(row=0, column=i, sticky=tk.W, padx=5)
        delay_frame = ttk.LabelFrame(main_frame, text="字幕时间调整（秒）", padding="10")
        delay_frame.pack(fill=tk.X, pady=5)
        ttk.Button(delay_frame, text="-", width=3, 
                  command=lambda: self.adjust_delay(-0.1)).pack(side=tk.LEFT, padx=5)
        ttk.Label(delay_frame, textvariable=self.subtitle_delay, width=5).pack(side=tk.LEFT)
        ttk.Button(delay_frame, text="+", width=3,
                  command=lambda: self.adjust_delay(0.1)).pack(side=tk.LEFT, padx=5)

        split_frame = ttk.LabelFrame(main_frame, text="分割长度", padding="10")
        split_frame.pack(fill=tk.X, pady=5)

        lengths = [6, 9, 12, 15]

        for i, minutes in enumerate(lengths):
            ttk.Radiobutton(split_frame, text=f"{minutes}分钟", variable=self.split_length,
                            value=str(minutes), command=self.check_ready).grid(row=0, column=i, sticky=tk.W, padx=5)
        ttk.Radiobutton(split_frame, text="不分割", variable=self.split_length,
                        value="0", command=self.check_ready).grid(row=0, column=len(lengths), sticky=tk.W, padx=5)


        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        ttk.Progressbar(progress_frame, variable=self.progress, maximum=100).pack(fill=tk.X)

        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, height=8, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)

        self.start_button = ttk.Button(button_frame, text="开始处理",
                                       command=self.start_processing, state=tk.DISABLED)
        self.start_button.pack(side=tk.RIGHT, padx=5)

        ttk.Button(button_frame, text="清除日志", command=self.clear_log).pack(side=tk.RIGHT)


        folder_frame.columnconfigure(1, weight=1)
        main_frame.columnconfigure(0, weight=1)

    def adjust_delay(self, delta):

        current = self.subtitle_delay.get()
        new_value = round(current + delta, 1)
        # 限制调整范围在±10秒之间
        if -10.0 <= new_value <= 10.0:
            self.subtitle_delay.set(new_value)

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)
            self.check_ready()
            self.log(f"已选择文件夹: {folder}")

    def check_ready(self):
        if self.folder_path.get() and self.burn_mode.get() and self.split_length.get():
            self.start_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.DISABLED)

    def start_processing(self):
        if self.process_running:
            return

        self.process_running = True
        self.start_button.config(state=tk.DISABLED)
        self.progress.set(0)
        self.log("开始处理...")

        threading.Thread(
            target=self.process_video,
            args=(self.folder_path.get(), self.burn_mode.get(), int(self.split_length.get())),
            daemon=True
        ).start()

    def process_video(self, folder, mode, split_minutes):
        try:
            video_file, subtitle_file, tail_file = self.find_input_files(folder)
            if not video_file or not subtitle_file:
                raise Exception("文件夹中必须包含一个视频文件和一个字幕文件")

            video_path = os.path.join(folder, video_file)
            subtitle_path = os.path.join(folder, subtitle_file)
            tail_path = os.path.join(folder, tail_file) if tail_file else None
            output_path = os.path.join(folder, "burned.mp4")

            # 先调整字幕时间，生成新的字幕文件
            adjusted_subtitle_path = self.adjust_subtitle_timestamps(subtitle_path, folder)

            self.log(f"开始烧录字幕: {mode} 模式")
            self.burn_subtitles(video_path, adjusted_subtitle_path, output_path, mode)
            self.progress.set(25)

            self.log(f"开始分割视频: 每 {split_minutes} 分钟一段")
            segments = self.split_video(output_path, folder, split_minutes)
            self.progress.set(50)

            if tail_path:
                self.log("检测到尾部视频，开始拼接...")
                # 获取主视频参数
                main_video_path = os.path.join(folder, "burned.mp4")
                main_params = self.get_video_params(main_video_path)
                # 传递当前烧录模式
                self.concat_tail(segments, tail_path, folder, main_params, mode)
                self.progress.set(75)

            self.cleanup_temp_files(output_path)
            self.progress.set(100)

            self.log("处理完成！")
            messagebox.showinfo("完成", "视频处理完成！")

        except Exception as e:
            self.log(f"错误: {str(e)}", error=True)
            messagebox.showerror("错误", f"处理失败: {str(e)}")
        finally:
            self.process_running = False
            self.log_queue.queue.clear()  # 清空残留日志
            self.root.after(100, lambda: self.start_button.config(state=tk.NORMAL))




    def adjust_subtitle_timestamps(self, subtitle_path, folder):
        try:
            delay = self.subtitle_delay.get()
            file_extension = os.path.splitext(subtitle_path)[1].lower()

            encodings = ['utf-8-sig', 'gbk', 'big5', 'utf-16']
            content = None
            for encoding in encodings:
                try:
                    with open(subtitle_path, 'r', encoding=encoding) as file:
                        content = file.readlines()
                    break
                except UnicodeDecodeError:
                    continue

            if content is None:
                raise Exception("无法解码字幕文件，请检查文件编码格式")

            new_content = []
            if file_extension == '.ass':
                for line in content:
                    if line.startswith('Dialogue'):
                        parts = line.split(',')
                        start_time_str = parts[1]
                        end_time_str = parts[2]
                        start_time = self.adjust_time(start_time_str, delay)
                        end_time = self.adjust_time(end_time_str, delay)
                        parts[1] = start_time
                        parts[2] = end_time
                        line = ','.join(parts)
                    new_content.append(line)

                # 创建新的字幕文件
                new_subtitle_path = os.path.join(folder, "adjusted_subtitles.ass")
                with open(new_subtitle_path, 'w', encoding='utf-8') as file:
                    file.writelines(new_content)
            
            elif file_extension == '.srt':
                # 处理SRT文件的时间戳
                for line in content:
                    timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', line)
                    if timestamp_match:
                        start_time_str, end_time_str = timestamp_match.groups()
                        start_time = self.adjust_time(start_time_str, delay)
                        end_time = self.adjust_time(end_time_str, delay)
                        line = f"{start_time} --> {end_time}\n"
                    new_content.append(line)

                new_subtitle_path = os.path.join(folder, "adjusted_subtitles.srt")
                with open(new_subtitle_path, 'w', encoding='utf-8') as file:
                    file.writelines(new_content)

            self.log(f"已生成新的字幕文件: {new_subtitle_path}")
            return new_subtitle_path
        except Exception as e:
            self.log(f"调整字幕时间失败: {str(e)}", error=True)
            raise


    


    def adjust_time(self, timestamp, delay):
        sep = "," if "," in timestamp else "."
        is_ass = (sep == ".")  # 判断是否是 ASS 格式
        
        ts = timestamp.replace(",", ".")
        parts = ts.split(".")
        time_part = parts[0]
        ms_part = parts[1] if len(parts) > 1 else "00"

        hours, minutes, seconds = map(int, time_part.split(":"))
        total = hours * 3600 + minutes * 60 + seconds + float(f"0.{ms_part}")  # 百分秒或毫秒都能解析
        total += delay
        if total < 0:
            total = 0.0

        h_new = int(total // 3600)
        total %= 3600
        m_new = int(total // 60)
        total %= 60
        s_new = int(total)
        fraction = total - s_new

        if is_ass:
            # .ass 用 2 位百分秒
            cs_new = int(round(fraction * 100))
            # 避免边界溢出（99 -> +1s）
            if cs_new >= 100:
                cs_new -= 100
                s_new += 1
            # 输出不补零小时
            return f"{h_new}:{m_new:02}:{s_new:02}.{cs_new:02}"
        else:
            # .srt 用 3 位毫秒
            ms_new = int(round(fraction * 1000))
            if ms_new >= 1000:
                ms_new -= 1000
                s_new += 1
            return f"{h_new:02}:{m_new:02}:{s_new:02},{ms_new:03}"

    









    def find_input_files(self, folder):
        video_ext = ('.mp4', '.mkv', '.avi', '.mov', '.flv')
        sub_ext = ('.srt', '.ass', '.ssa')

        video_files = []
        sub_files = []
        tail_files = []

        for f in os.listdir(folder):
            lower_f = f.lower()
            if lower_f.endswith(video_ext):
                if lower_f.startswith('tail'):
                    tail_files.append(f)
                else:
                    video_files.append(f)
            elif lower_f.endswith(sub_ext):
                sub_files.append(f)

        # 选择最大的视频文件
        video_file = max(video_files, key=lambda x: os.path.getsize(os.path.join(folder, x))) if video_files else None
        # 匹配同名字幕文件
        sub_file = next((s for s in sub_files if os.path.splitext(s)[0] == os.path.splitext(video_file)[0]), None) if video_file else None

        return (
            video_file,
            sub_file or (sub_files[0] if sub_files else None),
            tail_files[0] if tail_files else None
        )
  
    





    def burn_subtitles(self,input_file, subtitle_file, output_file, mode='balanced'):
        def has_high_end_audio(file_path):
            try:
                # Use ffprobe to get audio stream info in JSON
                cmd = [
                    "ffprobe", "-hide_banner", "-loglevel", "error",
                    "-select_streams", "a", "-show_streams",
                    "-print_format", "json", file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                info = json.loads(result.stdout)
            except Exception as e:
                print(f"Error running ffprobe: {e}")
                return False
            
            streams = info.get("streams", [])
            if not streams:
                return False
            
            # Assume the first audio stream is the main audio
            audio = streams[0]
            codec_name = audio.get("codec_name", "").lower()
            codec_long = audio.get("codec_long_name", "").lower()
            profile = audio.get("profile", "").lower()
            codec_tag = audio.get("codec_tag_string", "")
            channels = audio.get("channels", 0)
            tags = audio.get("tags", {}) or {}
            
            high_end = False
            # Dolby TrueHD (includes Atmos)
            if codec_name == "truehd":
                high_end = True
            # DTS variants (DTS-HD MA, DTS:X)
            if codec_name in ("dts", "dca"):
                if "dts-hd ma" in profile or "dts:x" in profile:
                    high_end = True
            if "dts-hd" in codec_long:
                high_end = True
            # Dolby Atmos (TrueHD with Atmos), indicated by A_TRUEHD tag
            if codec_tag == "A_TRUEHD":
                high_end = True
            # High channel count (>=9) likely object audio or Auro-3D
            if channels >= 9:
                high_end = True
            # Check tags for Auro-3D keyword
            for key in ("title", "handler_name", "comment"):
                if tags.get(key) and "auro" in tags[key].lower():
                    high_end = True
            return high_end

        # Detect high-end audio
        high_end_audio = has_high_end_audio(input_file)
        if high_end_audio:
            print("检测到高端音频格式，正在重新编码为 AAC (1920k)")

        # Build FFmpeg command
        subs_path = subtitle_file.replace("\\", "/").replace(":", "\\:")
        # Use single quotes around the path to handle spaces/colons in Windows paths
        subs_filter = f"subtitles='{subs_path}'"
        cmd = ["ffmpeg", "-hide_banner", "-y", "-i", input_file, "-vf", subs_filter]

        # Video encoding settings by mode
        cmd += ["-c:v", "libx264"]
        if mode == "lossless":
            cmd += ["-preset", "veryslow","-crf", "0"]
        elif mode == "fast":
            cmd += ["-preset", "fast", "-crf", "28"]
        else:  # balanced or default
            cmd += ["-preset", "medium", "-crf", "18"]

        # Audio processing
        if high_end_audio:
            # Re-encode audio to AAC with specified parameters
            cmd += ["-c:a", "aac", "-b:a", "1920k", "-ac", "6", "-ar", "48000"]
        else:
            # Copy original audio track
            cmd += ["-c:a", "copy"]

        # Set output file
        cmd.append(output_file)

        # Execute FFmpeg
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg execution failed: {e}")







    
  


    
    def split_video(self, video_path, folder, split_minutes):
        segment_folder = os.path.join(folder, "segments")
        os.makedirs(segment_folder, exist_ok=True)
        
        if split_minutes == 0:
            output_path = os.path.join(segment_folder, "full_video.mp4")
            cmd = [
                'ffmpeg', 
                '-i', video_path, 
                '-c', 'copy',  
                output_path
            ]
            self.log(f"执行不分割命令: {' '.join(cmd)}")
            self.run_command(cmd)
            return ["full_video.mp4"]  
        else:  
            cmd = [
                'ffmpeg', '-i', video_path,
                '-c', 'copy',
                '-f', 'segment',
                '-segment_time', str(split_minutes * 60),
                '-reset_timestamps', '1',
                os.path.join(segment_folder, 'part_%03d.mp4')
            ]
            self.log(f"执行分割命令: {' '.join(cmd)}")
            self.run_command(cmd)
            return sorted(
                f for f in os.listdir(segment_folder)
                if f.endswith('.mp4') and f.startswith('part_')
            )


    def concat_tail(self, segments, tail_path, folder, main_params, burn_mode):
        try:
            segment_folder = os.path.join(folder, "segments")
    
            transcoded_mp4 = self.transcode_tail(tail_path, segment_folder, main_params, burn_mode)
            transcoded_ts = os.path.join(segment_folder, "tail.ts")
            self.convert_to_ts(transcoded_mp4, transcoded_ts)

            for seg in segments:
                seg_mp4 = os.path.join(segment_folder, seg)
                seg_ts = os.path.join(segment_folder, f"temp_{seg}.ts")
                final_mp4 = os.path.join(segment_folder, f"final_{seg}")

                
                self.convert_to_ts(seg_mp4, seg_ts)
                self.concat_ts_files([seg_ts, transcoded_ts], final_mp4)
                for f in [seg_mp4, seg_ts]:
                    if os.path.exists(f):
                        os.remove(f)
            for f in [transcoded_mp4, transcoded_ts]:
                if os.path.exists(f):
                    os.remove(f)

        except Exception as e:
            self.log(f"拼接失败: {str(e)}", error=True)
            raise


    def convert_to_ts(self, input_file: str, output_ts: str):
        if not os.path.isfile(input_file):
            raise FileNotFoundError(f"Input file does not exist: {input_file}")
        try:
            probe_cmd = [
                'ffprobe', '-v', 'error', '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_name',
                '-of', 'default=nokey=1:noprint_wrappers=1',
                input_file
            ]
            self.log(f"Running ffprobe to detect audio codec: {' '.join(probe_cmd)}")
            result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
            audio_codec = result.stdout.strip().lower()
            if not audio_codec:
                self.log("No audio stream detected, proceeding with TS remux directly.")
                input_for_ts = input_file
            else:
                self.log(f"Detected audio codec: {audio_codec}")
                # List of audio codecs compatible with MPEG-TS
                ts_supported = {'aac', 'ac3', 'dts', 'mp2', 'mp3'}
                if audio_codec in ts_supported:
                    self.log(f"Audio codec '{audio_codec}' is supported by MPEG-TS. Skipping re-encoding.")
                    input_for_ts = input_file
                else:
                    self.log(f"Audio codec '{audio_codec}' is not supported by MPEG-TS. Re-encoding audio to AAC (192k)...")
                    # Prepare temporary output file path for re-encoded audio
                    base, ext = os.path.splitext(input_file)
                    temp_file = f"{base}_reencoded.mp4"
                    # Perform re-encoding: copy video, encode audio to AAC 192k
                    ffmpeg_cmd = [
                        'ffmpeg', '-y', '-i', input_file,
                        '-c:v', 'copy',
                        '-c:a', 'aac', '-b:a', '192k',
                        temp_file
                    ]
                    self.log(f"Running ffmpeg to transcode audio: {' '.join(ffmpeg_cmd)}")
                    subprocess.run(ffmpeg_cmd, check=True)
                    input_for_ts = temp_file
        except subprocess.CalledProcessError as e:
            self.log(f"Error detecting or transcoding audio: {e}")
            raise RuntimeError(f"Failed audio detection or transcoding: {e}")
        except Exception as e:
            self.log(f"Unexpected error: {e}")
            raise

        try:
            self.log(f"Remuxing to MPEG-TS: input='{input_for_ts}', output='{output_ts}'")
            ffmpeg_remux_cmd = [
                'ffmpeg', '-y', '-i', input_for_ts,
                '-c', 'copy', '-f', 'mpegts',
                output_ts
            ]
            self.log(f"Running ffmpeg command: {' '.join(ffmpeg_remux_cmd)}")
            subprocess.run(ffmpeg_remux_cmd, check=True)
            self.log(f"Successfully created TS file: {output_ts}")
        except subprocess.CalledProcessError as e:
            self.log(f"Error during TS remux: {e}")
            raise RuntimeError(f"Failed to remux to TS: {e}")
        finally:
            # Clean up temporary file if created
            if 'temp_file' in locals() and os.path.isfile(temp_file):
                try:
                    os.remove(temp_file)
                    self.log(f"Removed temporary file: {temp_file}")
                except Exception as e:
                    self.log(f"Could not remove temporary file '{temp_file}': {e}")


    def concat_ts_files(self, ts_files, output_file):
        try:
            list_file = os.path.join(os.path.dirname(output_file), "concat_list.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for ts in ts_files:
                    ts_path = os.path.normpath(ts).replace("\\", "/")
                    f.write(f"file '{ts_path}'\n")

            cmd = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',  
                '-i', list_file,
                '-c', 'copy',
                '-movflags', '+faststart',
                '-y', output_file
            ]
            self.run_command(cmd)
        finally:
            if os.path.exists(list_file):
                os.remove(list_file)


    def get_video_params(self, video_path):
        params = {
            'v_codec': 'libx264',
            'width': '1920',
            'height': '1080',
            'frame_rate': '23.98',
            'pix_fmt': 'yuv420p',
            'a_codec': 'aac',
            'sample_rate': '48000',
            'channels': '2',
            'a_bitrate': '192k',
            'has_audio': False
        }

        try:
            # 修正视频流参数解析
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=codec_name,width,height,r_frame_rate,pix_fmt',
                '-of', 'csv=p=0:nk=1',  # 确保字段顺序
                video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
            video_info = result.stdout.strip().split(',')
            
            # 严格字段顺序校验
            if len(video_info) >= 5:
                params.update({
                    'v_codec': video_info[0].strip() or 'libx264',
                    'width': video_info[1].strip() or '1920',
                    'height': video_info[2].strip() or '1080',
                    'frame_rate': self.safe_frame_rate(video_info[3].strip()),
                    'pix_fmt': video_info[4].strip() or 'yuv420p'
                })

            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_name,sample_rate,channels,bit_rate',
                '-of', 'csv=p=0:nk=1',
                video_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
            audio_info = result.stdout.strip().split(',')
            
            if len(audio_info) >= 4:  # 现在需要4个字段
                params.update({
                    'a_codec': audio_info[0].strip() if audio_info[0].strip() else 'aac',
                    'sample_rate': audio_info[1].strip() if audio_info[1].strip() else '48000',
                    'channels': audio_info[2].strip() if audio_info[2].strip() else '2',
                    'a_bitrate': f"{int(audio_info[3].strip())//1000}k" if audio_info[3].strip().isdigit() else '192k',
                    'has_audio': True
                })
            else:
                self.log("未检测到有效音频流，将禁用尾部音频")
                params['has_audio'] = False

        except Exception as e:
            self.log(f"参数解析警告: {str(e)}，使用默认音频参数", error=True)
            params['has_audio'] = False

        # 强制合法像素格式
        params['pix_fmt'] = params['pix_fmt'].split('/')[0].split(':')[0]  # 移除非法字符
        if params['pix_fmt'] not in ['yuv420p', 'yuvj420p', 'yuv422p']:
            params['pix_fmt'] = 'yuv420p'

        return params

    def safe_frame_rate(self, rate_str):
        try:
            if '/' in rate_str:
                num, den = rate_str.split('/')
                return f"{float(num)/float(den):.2f}"
            return f"{float(rate_str):.2f}"
        except:
            return '23.98'  # 默认常用帧率

    def transcode_tail(self, input_path, output_dir, main_params, burn_mode):
        output_path = os.path.join(output_dir, "transcoded_tail.mp4")
        
        # 视频参数
        video_params = [
            '-c:v', main_params['v_codec'],
            '-s', f"{main_params['width']}x{main_params['height']}",
            '-r', main_params['frame_rate'],
            '-pix_fmt', main_params['pix_fmt'],
            '-x264-params', 'nal-hrd=cbr'
        ]

        # 质量参数
        quality_params = {
            "lossless": ['-crf', '0', '-preset', 'slower'],
            "balanced": ['-crf', '18', '-preset', 'medium'],
            "fast": ['-crf', '28', '-preset', 'faster']
        }.get(burn_mode, ['-crf', '28', '-preset', 'faster'])

        audio_params = ['-an']  # 默认无音频
        if main_params['has_audio']:
            audio_params = [
                '-c:a', main_params['a_codec'],
                '-ar', main_params['sample_rate'],
                '-ac', main_params['channels'],
                '-b:a', main_params['a_bitrate'],
                '-strict', '-2'  # 确保支持非常规编码
            ]
            # 特殊编码格式处理
            if main_params['a_codec'].lower() in ['dts', 'ac3']:
                audio_params += ['-strict', '-2']

        cmd = [
            'ffmpeg', '-i', input_path,
            *video_params,
            *quality_params,
            *audio_params,
            '-vsync', 'cfr',
            '-avoid_negative_ts', 'make_zero',
            '-fflags', '+genpts',
            '-y', output_path
        ]

        self.log(f"转码命令: {' '.join(cmd)}")
        self.run_command(cmd)
        return output_path

    def parse_frame_rate(self, rate_str):
        try:
            if '/' in rate_str:
                numerator, denominator = map(int, rate_str.split('/'))
                return f"{round(numerator/denominator, 2):.2f}"
            return f"{float(rate_str):.2f}"
        except:
            return '30.00'

    def safe_path(self, raw_path):
        path = pathlib.Path(raw_path)
        return path.resolve().as_posix()

    def cleanup_temp_files(self, output_path):
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
                self.log("已清理临时烧录文件")
        except Exception as e:
            self.log(f"清理临时文件出错: {str(e)}", error=True)

    def run_command(self, cmd):
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                shell=True  # 在Windows下必须启用
            )

            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                self.log_queue.put(line.strip())
                print(line.strip())  # FFmpeg原始输出实时显示在控制台

            process.communicate()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode, 
                    cmd,
                    output=process.stdout
                )
        except Exception as e:
            self.log(f"命令执行失败: {str(e)}", error=True)
            raise

    def check_ffmpeg(self):
        try:
            subprocess.run(['ffmpeg', '-version'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except:
            return False


    def get_ffmpeg_version(self):
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True
            )
            version_line = result.stdout.split('\n')[0]
            return re.search(r'ffmpeg version (\d+\.\d+)', version_line).group(1)
        except:
            return "未知版本"


    def log(self, message, error=False):
        # 过滤concat调试信息
        if "[concat @" in message and not error:
            return
            
        timestamp = datetime.now().strftime("%H:%M:%S")
        msg = f"[{timestamp}] {message}"
        self.log_queue.put((msg, error))
        # 新增控制台输出
        print(msg)  # 所有日志信息输出到控制台

    def update_log(self):
        max_lines = 50  # 每次最多处理50条日志
        processed = 0
        while not self.log_queue.empty() and processed < max_lines:
            item = self.log_queue.get_nowait()
            if isinstance(item, tuple):
                msg, error = item
                self.log_text.insert(tk.END, msg + "\n")
                if error:
                    self.log_text.tag_add("error", "end-2l", "end-1c")
            else:
                self.log_text.insert(tk.END, item + "\n")
            processed += 1
        self.log_text.see(tk.END)
        self.root.after(50, self.update_log)  # 提高更新频率至50ms

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    try:
        from ttkthemes import ThemedTk
        root = ThemedTk(theme="arc")
    except ImportError:
        pass

    app = FFmpegApp(root)
    app.log_text.tag_config("error", foreground="red")
    root.mainloop()