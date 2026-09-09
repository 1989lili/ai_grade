; 好帮手AI阅卷 —— Inno Setup 安装包脚本
;
; 设计目标（对应"单文件交付 + 只解压一次"）：
;   1. 用户拿到的仍然是**一个 exe**（本脚本编译出的安装包）；
;   2. 首次双击：静默安装到 %LOCALAPPDATA%\AI_Grader（每用户安装，**不需要管理员**）；
;   3. 之后再双击同一个文件：检测到已安装且版本相同 → **直接启动程序并退出，不再重复解压**；
;   4. 版本不同 → 走升级安装（先清空旧目录，保证无残留）。
;
; 为什么能安全地装在每用户目录：运行时可写数据（预设 / 评分标准模板 / 标记位置 / 日志）
; 已全部改到 %APPDATA%\AI_Grader，见 backend/paths.py，安装目录本身不需要写权限。
;
; 编译（版本号可被 ISCC /DMyAppVersion=1.0.1 覆盖，见 make_installer.ps1 -Version）：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;   产物：Output\好帮手AI阅卷安装程序-<版本>.exe
;
; 前置：先跑 PyInstaller 生成 dist\AI_Grader\ 目录（build.spec，onedir 模式）。
; 注意：每次对外发布新版请递增版本号（/DMyAppVersion=…），
;   否则用户在已装同版本的机器上双击会被当成"已是最新"，直接启动而不会覆盖升级。

#define MyAppName      "好帮手AI阅卷"
#ifndef MyAppVersion
  #define MyAppVersion   "1.0.0"
#endif
#define MyAppExeName   "AI_Grader.exe"
#define MyAppPublisher "好帮手"
; 与 backend/launcher.py 里 CreateMutexW 的互斥体名保持一致（去掉 Local\ 前缀），
; 这样安装/卸载时 Inno 能识别"程序正在运行"并提示关闭，而不是覆盖失败。
#define MyAppMutex     "AI_Grader_9a3f2d71-e184-4e6e-bc28-8c5a1f6e9d4b"

[Setup]
; AppId 必须固定，升级/卸载靠它识别同一款产品
AppId={{B7E3A9C4-5D21-4F8A-9E6B-2C47D8A1F3E5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={localappdata}\AI_Grader
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
AppMutex={#MyAppMutex}

; 每用户安装，绝不弹 UAC
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 全程无向导页：双击即完成安装，观感接近绿色软件
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
AllowNoIcons=yes

; 压缩档位（打包速度依次 快→慢、体积 大→小）：
;   默认 = lzma2/normal   —— 日常迭代用，编译约 30s，体积略增 1~3MB
;   发布 = ISCC /DRelease —— 极限压缩，体积最小但编译 ~110s
;   调试 = ISCC /DFastCompile —— 几乎不压缩，编译秒级（产物 ~234MB，仅供本地快速验证）
#ifdef FastCompile
Compression=zip/1
OutputBaseFilename=好帮手AI阅卷安装程序-DEBUG
#else
  #ifdef Release
    Compression=lzma2/ultra64
    OutputBaseFilename=好帮手AI阅卷安装程序-{#MyAppVersion}
  #else
    Compression=lzma2/normal
    OutputBaseFilename=好帮手AI阅卷安装程序-{#MyAppVersion}
  #endif
#endif
SolidCompression=yes
DiskSpanning=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
SetupIconFile=
WizardStyle=modern

[Files]
; PyInstaller onedir 产物整目录打包
Source: "{#SourcePath}dist\AI_Grader\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"

[InstallDelete]
; 升级时先清空安装目录，避免旧版本残留文件与新版本混用
; （用户数据在 %APPDATA%\AI_Grader，不受影响）
Type: filesandordirs; Name: "{app}"

[Run]
; 安装完成后自动启动一次
Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; \
    Flags: nowait postinstall skipifsilent

[Code]
// 注意：这里必须写**单反括号**的 GUID，与 [Setup] 里 AppId 的值一致
// （[Setup] 中首括号要转义成 {{，所以不能直接用 SetupSetting("AppId") 拼键名，
//   那样取到的是脚本原文 "{{...}"，查注册表必然查不到）。
const
  UninstallRegKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{B7E3A9C4-5D21-4F8A-9E6B-2C47D8A1F3E5}_is1';
  VersionStampFile = 'install.ver';

function Bmt(V: Boolean): String;
begin
  if V then Result := 'True' else Result := 'False';
end;

// 兜底来源：安装目录内的版本戳文件（不依赖注册表视图，也防用户手动拷贝目录）
function InstalledVersionOnDisk: String;
var
  S: AnsiString;
begin
  Result := '';
  if LoadStringFromFile(ExpandConstant('{localappdata}\AI_Grader\' + VersionStampFile), S) then
    Result := Trim(String(S));
end;

function GetInstalledVersion: String;
var
  Ver: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, UninstallRegKey, 'DisplayVersion', Ver) then
    Result := Ver;
  if Result = '' then
    Result := InstalledVersionOnDisk;
end;

function InitializeSetup: Boolean;
var
  ExePath: String;
  Installed: String;
  ResultCode: Integer;
  Ok: Boolean;
begin
  Result := True;
  ExePath := ExpandConstant('{localappdata}\AI_Grader\{#MyAppExeName}');
  Installed := GetInstalledVersion;
  Log('[AI-GRADE] exe存在=' + Bmt(FileExists(ExePath)) + ' 已装版本=' + Installed);

  // 已安装且版本一致：直接启动，不做任何解压/覆盖
  if FileExists(ExePath) and (Installed = '{#MyAppVersion}') then
  begin
    Ok := Exec(ExePath, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
    Log('[AI-GRADE] Exec=' + Bmt(Ok) + ' ResultCode=' + IntToStr(ResultCode));
    if not Ok then
    begin
      Ok := ShellExec('open', ExePath, '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
      Log('[AI-GRADE] ShellExec=' + Bmt(Ok) + ' ResultCode=' + IntToStr(ResultCode));
    end;
    if not Ok then
      MsgBox('程序已安装，但自动启动失败。请从桌面"好帮手AI阅卷"图标启动。', mbError, MB_OK);
    Result := False;   // 静默退出安装流程，不显示"安装已中止"提示
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // 安装/升级完成后写版本戳，供下次双击时快速判定（注册表之外的兜底依据）
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\' + VersionStampFile), '{#MyAppVersion}', False);
end;
