package com.toxicgram.app;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.ColorFilter;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.RippleDrawable;
import android.content.res.ColorStateList;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.os.Build;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.text.Editable;
import android.text.format.DateFormat;
import java.util.Date;
import com.toxicgram.app.telegram.CombinedDrawable;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import android.text.InputType;
import android.text.InputFilter;
import org.json.JSONObject;
import org.json.JSONArray;
import android.os.Handler;
import android.os.Looper;
import android.content.ClipboardManager;
import android.content.ClipData;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final String BASE = "https://toxicgram-auth-production.up.railway.app";
    private int BG=0xff17212b, CARD=0xff202b36, INK=0xfff5f5f5, MUTED=0xff8295a6, PURPLE=0xff8c69de;
    private int CHAT=0xff0e1621, OUT=0xff473a70, LINE=0xff283542;
    private boolean light=false;
    private String ownName="";
    private boolean foreground=true;
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private String session, account;
    private LinearLayout root;
    private TextView status;
    private EditText number, code;
    private Button submit;
    private int page=0;
    private final Handler timer=new Handler(Looper.getMainLooper());
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        light=getPreferences(MODE_PRIVATE).getBoolean("light",false);
        palette();
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        if(Build.VERSION.SDK_INT>=30)getWindow().setDecorFitsSystemWindows(false);
        showLogin();
    }
    int dp(float v){return (int)(getResources().getDisplayMetrics().density*v+0.5f);}
    GradientDrawable shape(int color,int radius){
        GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;
    }
    void palette(){
        BG=light?0xffffffff:0xff17212b;CARD=light?0xfff1f3f5:0xff202b36;
        INK=light?0xff17212b:0xfff5f5f5;MUTED=light?0xff788692:0xff8295a6;
        PURPLE=light?0xff7250c8:0xff8c69de;CHAT=light?0xffe4e7f1:0xff0e1621;
        OUT=light?0xffe3d8fa:0xff473a70;LINE=light?0xffe7e9ed:0xff283542;
        getWindow().setStatusBarColor(BG);getWindow().setNavigationBarColor(BG);
        getWindow().getDecorView().setSystemUiVisibility(light?View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR:0);
    }
    void install(View v){
        if(Build.VERSION.SDK_INT>=30){
            FrameLayout safe=new FrameLayout(this);safe.setBackgroundColor(BG);
            safe.addView(v,new FrameLayout.LayoutParams(-1,-1));
            safe.setOnApplyWindowInsetsListener((view,insets)->{
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout()|WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);return insets;
            });
            setContentView(safe);safe.requestApplyInsets();
        }else setContentView(v);
    }
    void screen(){
        page++;timer.removeCallbacksAndMessages(null);
        ScrollView sc=new ScrollView(this);sc.setFillViewport(true);sc.setBackgroundColor(BG);
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(dp(24),dp(48),dp(24),dp(28));
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        sc.addView(root,new ScrollView.LayoutParams(-1,-2));install(sc);
    }
    TextView text(String s,int size,int color,boolean bold,int margin){
        TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);t.setGravity(Gravity.CENTER);
        if(bold)t.setTypeface(Typeface.DEFAULT,Typeface.BOLD);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(margin);root.addView(t,p);return t;
    }
    EditText field(String hint,int type,int length){
        EditText e=new EditText(this);e.setTextColor(INK);e.setHintTextColor(MUTED);e.setHint(hint);e.setTextSize(17);
        e.setSingleLine();e.setInputType(type);e.setFilters(new InputFilter[]{new InputFilter.LengthFilter(length)});
        e.setPadding(dp(16),0,dp(16),0);e.setBackground(shape(CARD,16));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(60));p.bottomMargin=dp(12);root.addView(e,p);return e;
    }
    Button button(String label){
        Button b=new Button(this);b.setText(label);b.setAllCaps(false);b.setTextColor(Color.WHITE);b.setTextSize(16);
        b.setBackground(shape(PURPLE,16));
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(54));p.topMargin=dp(12);p.bottomMargin=dp(12);root.addView(b,p);return b;
    }
    void showLogin(){
        screen();
        TextView logo=text("T",38,Color.WHITE,true,24);logo.setBackground(shape(PURPLE,24));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(dp(84),dp(84));lp.bottomMargin=dp(24);logo.setLayoutParams(lp);
        text("Toxicgram",32,INK,true,12);
        text("Вход в свой аккаунт",20,INK,true,8);
        text("Откройте бота Toxicgram в Telegram, отправьте /code и введите выданный виртуальный номер и код.",15,MUTED,false,28);
        number=field("TG-1234-5678",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS,16);
        code=field("Код из 6 цифр",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_VARIATION_PASSWORD,6);
        submit=button("Войти");
        status=text("",14,MUTED,false,16);
        text("Используйте только код Toxicgram, не код входа в Telegram.",13,MUTED,false,16);
        submit.setOnClickListener(v->login());
    }
    void login(){
        String n=number.getText().toString().trim().toUpperCase(Locale.ROOT), c=code.getText().toString().trim();
        if(!n.matches("TG-[0-9]{4}-[0-9]{4}")||!c.matches("[0-9]{6}")){status.setText("Проверьте формат номера и кода.");return;}
        submit.setEnabled(false);status.setText("Подключение...");
        network.execute(()->{
            try{
                JSONObject body=new JSONObject().put("number",n).put("code",c);
                JSONObject response=request("POST","/v1/auth/verify",body,null);
                String token=response.getString("access_token"), id=response.getString("number");
                JSONObject profile=request("GET","/v1/me",null,token);
                if(!id.equals(profile.getString("number")))throw new IOException("Account mismatch");
                runOnUiThread(()->{if(isFinishing()||isDestroyed())return;session=token;account=id;showAccount();});
            }catch(Exception e){
                runOnUiThread(()->{if(isFinishing()||isDestroyed())return;submit.setEnabled(true);status.setText(e instanceof ApiError?(((ApiError)e).status==429?"Слишком много попыток. Повторите позже.":((ApiError)e).status==401?"Неверный или просроченный код. Получите новый.":"Сервер временно недоступен."):"Не удалось подключиться к серверу.");});
            }
        });
    }
    interface Result { void accept(JSONObject data) throws Exception; }
    void call(String method,String path,JSONObject body,Result done,TextView error,Button busy){
        final int current=page;final String token=session;
        if(busy!=null)busy.setEnabled(false);
        network.execute(()->{
            try {
                JSONObject data=request(method,path,body,token);
                runOnUiThread(()->{
                    if(isDestroyed()||current!=page)return;
                    if(busy!=null)busy.setEnabled(true);
                    try{done.accept(data);}catch(Exception e){if(error!=null)error.setText("Не удалось обработать ответ.");}
                });
            } catch(Exception e){
                runOnUiThread(()->{
                    if(isDestroyed()||current!=page)return;
                    if(busy!=null)busy.setEnabled(true);
                    if(e instanceof ApiError&&((ApiError)e).status==401){session=null;account=null;showLogin();status.setText("Сеанс завершён. Войдите снова.");return;}
                    if(error!=null)error.setText(e instanceof ApiError&&((ApiError)e).status==404?"Аккаунт не найден.":e instanceof ApiError&&((ApiError)e).status==429?"Слишком много запросов.":"Ошибка соединения. Повторите позже.");
                });
            }
        });
    }
    JSONObject data(String key,String value){
        JSONObject o=new JSONObject();try{o.put(key,value);}catch(Exception ignored){}return o;
    }
    LinearLayout column(){LinearLayout l=new LinearLayout(this);l.setOrientation(LinearLayout.VERTICAL);return l;}
    LinearLayout horizontal(){LinearLayout l=new LinearLayout(this);l.setGravity(Gravity.CENTER_VERTICAL);return l;}
    TextView label(String s,int size,int color,boolean bold){
        TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);
        if(bold)t.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));return t;
    }
    void line(LinearLayout parent,int left){
        View v=new View(this);v.setBackgroundColor(LINE);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(1));p.leftMargin=dp(left);parent.addView(v,p);
    }
    Drawable ripple(int color,int radius){return new RippleDrawable(ColorStateList.valueOf(0x228e95ae),shape(color,radius),shape(Color.WHITE,radius));}
    class Glyph extends Drawable {
        final String kind; final int color; final Paint p=new Paint(3);
        Glyph(String k,int c){kind=k;color=c;}
        public int getIntrinsicWidth(){return dp(24);}public int getIntrinsicHeight(){return dp(24);}
        @Override public void draw(Canvas canvas){
            Rect b=getBounds();canvas.save();canvas.translate(b.left,b.top);canvas.scale(b.width()/24f,b.height()/24f);
            p.setColor(color);p.setStrokeWidth(2);p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);p.setStyle(Paint.Style.STROKE);
            switch(kind){
                case "menu":for(int y=6;y<=18;y+=6)canvas.drawLine(3,y,21,y,p);break;
                case "back":canvas.drawLine(4,12,20,12,p);canvas.drawLine(4,12,11,5,p);canvas.drawLine(4,12,11,19,p);break;
                case "search":canvas.drawCircle(10,10,6,p);canvas.drawLine(15,15,21,21,p);break;
                case "edit":canvas.drawLine(4,20,8,19,p);canvas.drawLine(8,19,20,7,p);canvas.drawLine(20,7,17,4,p);canvas.drawLine(17,4,5,16,p);canvas.drawLine(5,16,4,20,p);canvas.drawLine(15,6,18,9,p);break;
                case "send":p.setStyle(Paint.Style.FILL);Path a=new Path();a.moveTo(2,3);a.lineTo(23,12);a.lineTo(2,21);a.lineTo(6,13);a.lineTo(16,12);a.lineTo(6,11);a.close();canvas.drawPath(a,p);break;
                case "more":p.setStyle(Paint.Style.FILL);for(int y=5;y<=19;y+=7)canvas.drawCircle(12,y,1.7f,p);break;
                case "check":canvas.drawLine(4,12,9,17,p);canvas.drawLine(9,17,20,6,p);break;
            }
            canvas.restore();
        }
        public void setAlpha(int a){p.setAlpha(a);}public void setColorFilter(ColorFilter f){p.setColorFilter(f);}public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
    ImageButton icon(String kind,String desc,Runnable click){
        ImageButton b=new ImageButton(this);b.setImageDrawable(new Glyph(kind,MUTED));b.setScaleType(ImageView.ScaleType.CENTER);
        b.setBackground(ripple(Color.TRANSPARENT,24));b.setContentDescription(desc);b.setOnClickListener(v->click.run());return b;
    }
    ImageButton circleAction(String kind,String desc,Runnable click){
        ImageButton b=new ImageButton(this);
        CombinedDrawable d=new CombinedDrawable(shape(PURPLE,100),new Glyph(kind,Color.WHITE));
        d.setCustomSize(dp(56),dp(56));d.setIconSize(dp(24),dp(24));b.setImageDrawable(d);
        b.setScaleType(ImageView.ScaleType.FIT_CENTER);b.setPadding(0,0,0,0);b.setBackgroundColor(Color.TRANSPARENT);
        b.setContentDescription(desc);b.setOnClickListener(v->click.run());return b;
    }
    TextView avatar(String name,int size){
        int[] colors={0xff658ed1,0xffa277ce,0xffd18a70,0xff4da99b,0xff779b58,0xffb96e98};
        String clean=name==null?"":name.trim();String initial=clean.isEmpty()?"?":new String(Character.toChars(clean.codePointAt(0))).toUpperCase(Locale.ROOT);
        TextView a=label(initial,size,Color.WHITE,true);a.setGravity(Gravity.CENTER);a.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{colors[Math.floorMod(clean.hashCode(),colors.length)],0xff62528d}));((GradientDrawable)a.getBackground()).setCornerRadius(dp(100));return a;
    }
    LinearLayout pageLayout(){
        page++;timer.removeCallbacksAndMessages(null);
        LinearLayout layout=column();layout.setBackgroundColor(BG);root=layout;install(layout);return layout;
    }
    LinearLayout toolbar(LinearLayout layout,String title,String sub,Runnable back){
        LinearLayout bar=horizontal();bar.setBackgroundColor(BG);bar.setPadding(dp(4),0,dp(4),0);
        if(back!=null)bar.addView(icon("back","Назад",back),new LinearLayout.LayoutParams(dp(48),dp(56)));
        LinearLayout titles=column();titles.setPadding(dp(12),0,0,0);titles.setGravity(Gravity.CENTER_VERTICAL);
        TextView heading=label(title,20,INK,true);heading.setSingleLine();heading.setEllipsize(TextUtils.TruncateAt.END);titles.addView(heading);
        if(sub!=null){TextView small=label(sub,13,MUTED,false);small.setSingleLine();titles.addView(small);}
        bar.addView(titles,new LinearLayout.LayoutParams(0,dp(56),1));layout.addView(bar,new LinearLayout.LayoutParams(-1,dp(56)));return bar;
    }
    void copyId(){
        ((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Toxicgram ID",account));
        Toast.makeText(this,"Номер скопирован",Toast.LENGTH_SHORT).show();
    }
    void notice(String s){Toast.makeText(this,s,Toast.LENGTH_SHORT).show();}
    void hideKeyboard(){View focused=getCurrentFocus();if(focused!=null)((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(focused.getWindowToken(),0);}
    void askPeer(){
        EditText e=new EditText(this);e.setSingleLine();e.setHint("TG-1234-5678");e.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);e.setFilters(new InputFilter[]{new InputFilter.LengthFilter(16)});
        FrameLayout wrapper=new FrameLayout(this);wrapper.setPadding(dp(24),dp(12),dp(24),0);wrapper.addView(e,new FrameLayout.LayoutParams(-1,-2));
        android.app.AlertDialog dialog=new android.app.AlertDialog.Builder(this).setTitle("Новый чат").setMessage("Введите виртуальный номер пользователя").setView(wrapper).setNegativeButton("Отмена",null).setPositiveButton("Открыть",null).create();
        dialog.setOnShowListener(v->dialog.getButton(-1).setOnClickListener(w->{
            String id=e.getText().toString().trim().toUpperCase(Locale.ROOT);
            if(!id.matches("TG-[0-9]{4}-[0-9]{4}")){e.setError("Неверный формат");return;}
            TextView error=new TextView(this);
            final int current=page;final String token=session;dialog.getButton(-1).setEnabled(false);
            network.execute(()->{try{JSONObject d=request("GET","/v1/users/"+id,null,token);runOnUiThread(()->{if(page!=current||isDestroyed()||!dialog.isShowing())return;dialog.dismiss();hideKeyboard();showChat(id,d.optString("name",id));});}catch(Exception ex){runOnUiThread(()->{if(page!=current||isDestroyed()||!dialog.isShowing())return;dialog.getButton(-1).setEnabled(true);e.setError(ex instanceof ApiError&&((ApiError)ex).status==404?"Пользователь не найден":"Не удалось подключиться");});}});
        }));dialog.show();
    }
    void drawer(){
        final android.app.Dialog dialog=new android.app.Dialog(this);
        LinearLayout menu=column();menu.setBackgroundColor(BG);
        LinearLayout head=column();head.setBackgroundColor(CARD);head.setPadding(dp(20),dp(24),dp(20),dp(18));
        head.addView(avatar(ownName.isEmpty()?account:ownName,28),new LinearLayout.LayoutParams(dp(64),dp(64)));
        TextView nm=label(ownName.isEmpty()?"Toxicgram":ownName,18,INK,true);nm.setPadding(0,dp(12),0,dp(4));head.addView(nm);head.addView(label(account,14,MUTED,false));head.setOnClickListener(v->{dialog.dismiss();copyId();});menu.addView(head);
        String[] names={"Мой профиль","Новый чат","Скопировать номер",light?"Тёмная тема":"Светлая тема","Выйти"};
        String[] glyphs={"◉","✎","⧉",light?"☾":"☀","↪"};
        for(int i=0;i<names.length;i++){
            final int action=i;LinearLayout row=horizontal();row.setPadding(dp(20),0,dp(20),0);row.setBackground(ripple(BG,0));
            TextView g=label(glyphs[i],24,MUTED,false);row.addView(g,new LinearLayout.LayoutParams(dp(46),-2));row.addView(label(names[i],16,INK,true));menu.addView(row,new LinearLayout.LayoutParams(-1,dp(54)));
            row.setOnClickListener(v->{dialog.dismiss();switch(action){case 0:showProfile();break;case 1:askPeer();break;case 2:copyId();break;case 3:light=!light;getPreferences(MODE_PRIVATE).edit().putBoolean("light",light).apply();palette();showAccount();break;case 4:confirmLogout();break;}});
        }
        dialog.setContentView(menu);if(dialog.getWindow()!=null){dialog.getWindow().setBackgroundDrawableResource(android.R.color.transparent);dialog.getWindow().setGravity(Gravity.LEFT|Gravity.TOP);dialog.getWindow().addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);dialog.getWindow().setDimAmount(.45f);}
        dialog.show();if(dialog.getWindow()!=null)dialog.getWindow().setLayout(Math.min(dp(320),(int)(getResources().getDisplayMetrics().widthPixels*.85)), -1);
    }
    void confirmLogout(){
        new android.app.AlertDialog.Builder(this).setTitle("Выйти из аккаунта?").setMessage("Для следующего входа потребуется новый код от бота.").setNegativeButton("Отмена",null).setPositiveButton("Выйти",(d,w)->{
            TextView err=new TextView(this);call("POST","/v1/auth/logout",null,x->{session=null;account=null;ownName="";showLogin();},err,null);
        }).show();
    }
    String timeLabel(long seconds){
        if(seconds<=0)return "";Date d=new Date(seconds*1000L);
        java.util.Calendar now=java.util.Calendar.getInstance(),day=java.util.Calendar.getInstance();day.setTime(d);
        return DateFormat.format(now.get(java.util.Calendar.YEAR)==day.get(java.util.Calendar.YEAR)&&now.get(java.util.Calendar.DAY_OF_YEAR)==day.get(java.util.Calendar.DAY_OF_YEAR)?"HH:mm":"dd.MM",d).toString();
    }
    void showAccount(){
        LinearLayout layout=pageLayout();final int current=page;
        LinearLayout bar=horizontal();bar.setPadding(dp(4),0,dp(4),0);bar.addView(icon("menu","Меню",()->drawer()),new LinearLayout.LayoutParams(dp(48),dp(56)));
        TextView title=label("Toxicgram",21,INK,true);bar.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        EditText search=new EditText(this);search.setTextColor(INK);search.setHintTextColor(MUTED);search.setHint("Поиск");search.setTextSize(17);search.setSingleLine();search.setBackgroundColor(Color.TRANSPARENT);search.setVisibility(View.GONE);bar.addView(search,new LinearLayout.LayoutParams(0,dp(48),1));
        bar.addView(icon("search","Поиск",()->{boolean on=search.getVisibility()!=View.VISIBLE;search.setVisibility(on?View.VISIBLE:View.GONE);title.setVisibility(on?View.GONE:View.VISIBLE);if(on){search.requestFocus();((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(search,InputMethodManager.SHOW_IMPLICIT);}else{search.setText("");hideKeyboard();}}),new LinearLayout.LayoutParams(dp(48),dp(56)));
        layout.addView(bar,new LinearLayout.LayoutParams(-1,dp(56)));
        TextView tab=label("Все чаты",15,PURPLE,true);tab.setPadding(dp(20),dp(12),0,dp(10));layout.addView(tab);
        View indicator=new View(this);indicator.setBackground(shape(PURPLE,3));LinearLayout.LayoutParams ip=new LinearLayout.LayoutParams(dp(92),dp(3));ip.leftMargin=dp(16);layout.addView(indicator,ip);line(layout,0);
        TextView info=label("",13,MUTED,false);info.setGravity(Gravity.CENTER);layout.addView(info);
        FrameLayout area=new FrameLayout(this);layout.addView(area,new LinearLayout.LayoutParams(-1,0,1));
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);LinearLayout list=column();list.setPadding(0,0,0,dp(84));scroll.addView(list,new ScrollView.LayoutParams(-1,-2));area.addView(scroll,new FrameLayout.LayoutParams(-1,-1));
        ImageButton fab=circleAction("edit","Новый чат",()->askPeer());FrameLayout.LayoutParams fp=new FrameLayout.LayoutParams(dp(56),dp(56),Gravity.BOTTOM|Gravity.RIGHT);fp.setMargins(0,0,dp(16),dp(18));area.addView(fab,fp);fab.setElevation(dp(5));
        final JSONArray[] cache={new JSONArray()};final String[] snapshot={""};final boolean[] loading={false};
        Runnable render=()->{
            list.removeAllViews();String q=search.getText().toString().trim().toLowerCase(Locale.ROOT);int visible=0;
            for(int i=0;i<cache[0].length();i++){
                JSONObject row=cache[0].optJSONObject(i);if(row==null)continue;
                String id=row.optString("number"),name=row.optString("name",id),msg=row.optString("text");
                if(!q.isEmpty()&&!(name+" "+id+" "+msg).toLowerCase(Locale.ROOT).contains(q))continue;visible++;
                LinearLayout cell=horizontal();cell.setBackground(ripple(BG,0));cell.setPadding(dp(12),0,dp(16),0);
                cell.addView(avatar(name,23),new LinearLayout.LayoutParams(dp(54),dp(54)));
                LinearLayout content=column();content.setPadding(dp(12),0,0,0);
                LinearLayout top=horizontal();TextView nm=label(name,16,INK,true);nm.setSingleLine();nm.setEllipsize(TextUtils.TruncateAt.END);top.addView(nm,new LinearLayout.LayoutParams(0,-2,1));TextView timestamp=label(timeLabel(row.optLong("created")),12,MUTED,false);top.addView(timestamp);
                content.addView(top);TextView preview=label(msg,14,MUTED,false);preview.setSingleLine();preview.setEllipsize(TextUtils.TruncateAt.END);preview.setPadding(0,dp(4),0,0);content.addView(preview);
                cell.addView(content,new LinearLayout.LayoutParams(0,-2,1));list.addView(cell,new LinearLayout.LayoutParams(-1,dp(76)));line(list,78);cell.setOnClickListener(v->{hideKeyboard();showChat(id,name);});
            }
            if(visible==0){LinearLayout empty=column();empty.setGravity(Gravity.CENTER);empty.setPadding(dp(28),dp(70),dp(28),dp(20));TextView t=label(q.isEmpty()?"Пока нет чатов":"Ничего не найдено",20,INK,true);t.setGravity(Gravity.CENTER);empty.addView(t);TextView hint=label(q.isEmpty()?"Начните переписку по виртуальному номеру друга.":"Введите точный номер в новом чате.",15,MUTED,false);hint.setPadding(0,dp(10),0,0);hint.setGravity(Gravity.CENTER);empty.addView(hint);list.addView(empty,new LinearLayout.LayoutParams(-1,-2));}
        };
        search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int n,int f){}public void onTextChanged(CharSequence s,int a,int b,int n){render.run();}public void afterTextChanged(Editable e){}});
        Runnable load=()->{if(loading[0])return;loading[0]=true;String token=session;network.execute(()->{try{JSONObject d=request("GET","/v1/chats",null,token);runOnUiThread(()->{loading[0]=false;if(isDestroyed()||page!=current)return;info.setText("");JSONArray arr=d.optJSONArray("chats");if(arr!=null){String value=arr.toString();if(!value.equals(snapshot[0])){snapshot[0]=value;cache[0]=arr;render.run();}}});}catch(Exception e){runOnUiThread(()->{loading[0]=false;if(isDestroyed()||page!=current)return;if(e instanceof ApiError&&((ApiError)e).status==401){session=null;account=null;showLogin();return;}info.setText("Подключение…");});}});};
        call("GET","/v1/profile",null,d->ownName=d.optString("name",account),null,null);
        render.run();load.run();timer.postDelayed(new Runnable(){public void run(){if(isDestroyed()||page!=current)return;if(foreground)load.run();timer.postDelayed(this,5000);}},5000);
    }
    void showProfile(){
        LinearLayout layout=pageLayout();LinearLayout bar=toolbar(layout,"Профиль",null,()->showAccount());line(layout,0);
        LinearLayout main=column();main.setPadding(dp(22),dp(32),dp(22),dp(20));main.setGravity(Gravity.CENTER_HORIZONTAL);layout.addView(main,new LinearLayout.LayoutParams(-1,-2));
        TextView photo=avatar(ownName.isEmpty()?account:ownName,42);main.addView(photo,new LinearLayout.LayoutParams(dp(100),dp(100)));
        TextView title=label(ownName.isEmpty()?account:ownName,23,INK,true);title.setPadding(0,dp(16),0,dp(8));main.addView(title);
        TextView id=label(account,16,PURPLE,false);id.setOnClickListener(v->copyId());main.addView(id);
        root=main;TextView hint=text("Имя пользователя",13,MUTED,false,8);hint.setPadding(0,dp(30),0,0);
        EditText name=field("Имя",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES,64);name.setText(ownName);TextView info=text("",14,MUTED,false,8);
        Button save=button("Сохранить");call("GET","/v1/profile",null,d->{name.setText(d.getString("name"));},info,save);
        save.setOnClickListener(v->{String value=name.getText().toString().trim();if(value.isEmpty()){name.setError("Введите имя");return;}call("PUT","/v1/profile",data("name",value),d->{ownName=d.optString("name",value);hideKeyboard();showAccount();},info,save);});
    }
    void showChat(String peer,String name){
        LinearLayout layout=pageLayout();final int current=page;
        LinearLayout bar=horizontal();bar.addView(icon("back","Назад",()->{hideKeyboard();showAccount();}),new LinearLayout.LayoutParams(dp(48),dp(56)));
        bar.addView(avatar(name,19),new LinearLayout.LayoutParams(dp(40),dp(40)));
        LinearLayout titles=column();titles.setPadding(dp(12),0,0,0);TextView heading=label(name,18,INK,true);heading.setSingleLine();heading.setEllipsize(TextUtils.TruncateAt.END);titles.addView(heading);titles.addView(label(peer,12,MUTED,false));bar.addView(titles,new LinearLayout.LayoutParams(0,-2,1));
        ImageButton more=icon("more","Меню чата",()->{});more.setOnClickListener(v->{PopupMenu popup=new PopupMenu(this,more);popup.getMenu().add("Скопировать номер");popup.setOnMenuItemClickListener(item->{((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Toxicgram ID",peer));notice("Номер скопирован");return true;});popup.show();});bar.addView(more,new LinearLayout.LayoutParams(dp(48),dp(56)));layout.addView(bar,new LinearLayout.LayoutParams(-1,dp(56)));line(layout,0);
        FrameLayout backdrop=new FrameLayout(this);backdrop.setBackgroundColor(CHAT);layout.addView(backdrop,new LinearLayout.LayoutParams(-1,0,1));
        View pattern=new View(this){final Paint p=new Paint(3);@Override protected void onDraw(Canvas canvas){super.onDraw(canvas);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(dp(1));p.setColor(light?0x177250c8:0x163c6c95);for(int y=dp(25);y<getHeight();y+=dp(72))for(int x=dp(22);x<getWidth();x+=dp(76)){int shift=(y/dp(72)%2)*dp(20);canvas.drawCircle(x+shift,y,dp(10),p);canvas.drawLine(x+shift-dp(5),y,x+shift+dp(5),y,p);}}};backdrop.addView(pattern,new FrameLayout.LayoutParams(-1,-1));
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);LinearLayout history=column();history.setPadding(dp(10),dp(12),dp(10),dp(12));history.setGravity(Gravity.BOTTOM);scroll.addView(history,new ScrollView.LayoutParams(-1,-2));backdrop.addView(scroll,new FrameLayout.LayoutParams(-1,-1));
        TextView info=label("",12,MUTED,false);info.setGravity(Gravity.CENTER);layout.addView(info);
        LinearLayout composerRow=horizontal();composerRow.setPadding(dp(8),dp(6),dp(8),dp(6));composerRow.setBackgroundColor(BG);
        EditText composer=new EditText(this);composer.setTextColor(INK);composer.setHintTextColor(MUTED);composer.setHint("Сообщение");composer.setTextSize(16);composer.setMinLines(1);composer.setMaxLines(4);composer.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);composer.setFilters(new InputFilter[]{new InputFilter.LengthFilter(4000)});composer.setPadding(dp(15),dp(12),dp(15),dp(12));composer.setBackground(shape(CARD,24));composerRow.addView(composer,new LinearLayout.LayoutParams(0,-2,1));
        ImageButton send=circleAction("send","Отправить сообщение",()->{});LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(dp(46),dp(46));sp.leftMargin=dp(6);composerRow.addView(send,sp);layout.addView(composerRow,new LinearLayout.LayoutParams(-1,-2));
        final long[] last={-1};final boolean[] loading={false};
        Runnable load=()->{if(loading[0])return;loading[0]=true;String token=session;network.execute(()->{try{JSONObject d=request("GET","/v1/chats/"+peer+"/messages",null,token);runOnUiThread(()->{
            loading[0]=false;if(isDestroyed()||page!=current)return;info.setText("");JSONArray arr=d.optJSONArray("messages");if(arr==null)return;long newest=arr.length()==0?0:arr.optJSONObject(arr.length()-1).optLong("id");if(newest==last[0])return;
            boolean bottom=last[0]<0||scroll.getScrollY()+scroll.getHeight()>=history.getHeight()-dp(100);last[0]=newest;history.removeAllViews();String previousDay="";
            for(int i=0;i<arr.length();i++){
                JSONObject msg=arr.optJSONObject(i);if(msg==null)continue;boolean mine=account.equals(msg.optString("sender"));long created=msg.optLong("created");String day=DateFormat.format("dd MMMM yyyy",new Date(created*1000L)).toString();
                if(!day.equals(previousDay)){TextView date=label(day,12,Color.WHITE,true);date.setGravity(Gravity.CENTER);date.setPadding(dp(12),dp(5),dp(12),dp(5));date.setBackground(shape(0xff64758a,16));LinearLayout.LayoutParams datep=new LinearLayout.LayoutParams(-2,-2);datep.gravity=Gravity.CENTER;datep.setMargins(0,dp(8),0,dp(12));history.addView(date,datep);previousDay=day;}
                LinearLayout bubble=column();bubble.setPadding(dp(12),dp(8),dp(10),dp(6));GradientDrawable bg=new GradientDrawable();bg.setColor(mine?OUT:CARD);float rad=dp(16),tail=dp(4);bg.setCornerRadii(mine?new float[]{rad,rad,rad,rad,tail,tail,rad,rad}:new float[]{rad,rad,rad,rad,rad,rad,tail,tail});bubble.setBackground(bg);
                TextView body=label(msg.optString("text"),16,INK,false);body.setMaxWidth(Math.min(dp(310),(int)(getResources().getDisplayMetrics().widthPixels*.76)));body.setTextIsSelectable(true);bubble.addView(body,new LinearLayout.LayoutParams(-2,-2));
                TextView stamp=label(DateFormat.format("HH:mm",new Date(created*1000L)).toString()+(mine?"  ✓":""),11,mine?PURPLE:MUTED,false);stamp.setGravity(Gravity.RIGHT);LinearLayout.LayoutParams tp=new LinearLayout.LayoutParams(-1,-2);tp.topMargin=dp(3);bubble.addView(stamp,tp);LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-2,-2);bp.gravity=mine?Gravity.RIGHT:Gravity.LEFT;bp.bottomMargin=dp(5);history.addView(bubble,bp);
            }
            if(bottom)scroll.post(()->scroll.fullScroll(View.FOCUS_DOWN));
        });}catch(Exception e){runOnUiThread(()->{loading[0]=false;if(isDestroyed()||page!=current)return;if(e instanceof ApiError&&((ApiError)e).status==401){session=null;account=null;showLogin();return;}info.setText("Подключение…");});}});};
        send.setOnClickListener(v->{String value=composer.getText().toString().trim();if(value.isEmpty())return;send.setEnabled(false);JSONObject body=data("recipient",peer);try{body.put("text",value);}catch(Exception ignored){}String token=session;network.execute(()->{try{request("POST","/v1/messages",body,token);runOnUiThread(()->{if(isDestroyed()||page!=current)return;send.setEnabled(true);if(composer.getText().toString().trim().equals(value))composer.setText("");load.run();});}catch(Exception e){runOnUiThread(()->{if(isDestroyed()||page!=current)return;send.setEnabled(true);info.setText("Сообщение не отправлено. Повторите попытку.");});}});});
        load.run();timer.postDelayed(new Runnable(){public void run(){if(isDestroyed()||page!=current)return;if(foreground)load.run();timer.postDelayed(this,5000);}},5000);
    }
    @Override protected void onResume(){super.onResume();foreground=true;}
    @Override protected void onPause(){foreground=false;super.onPause();}
    @Override public void onBackPressed(){if(session!=null){showAccount();}else super.onBackPressed();}
    static class ApiError extends IOException{int status;ApiError(int s){status=s;}}
    JSONObject request(String method,String path,JSONObject body,String token)throws Exception{
        HttpsURLConnection conn=(HttpsURLConnection)new URL(BASE+path).openConnection();
        try{
            conn.setConnectTimeout(15000);conn.setReadTimeout(15000);conn.setRequestMethod(method);
            conn.setInstanceFollowRedirects(false);conn.setRequestProperty("Accept","application/json");
            if(token!=null)conn.setRequestProperty("Authorization","Bearer "+token);
            if(body!=null){conn.setDoOutput(true);conn.setRequestProperty("Content-Type","application/json");try(OutputStream out=conn.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}
            int response=conn.getResponseCode();if(response<200||response>=300)throw new ApiError(response);
            try(InputStream in=conn.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] b=new byte[4096];int count;while((count=in.read(b))!=-1){if(out.size()+count>2097152)throw new IOException("Too large");out.write(b,0,count);}
                return new JSONObject(out.toString("UTF-8"));
            }
        }finally{conn.disconnect();}
    }
    @Override protected void onDestroy(){timer.removeCallbacksAndMessages(null);network.shutdownNow();super.onDestroy();}
}
