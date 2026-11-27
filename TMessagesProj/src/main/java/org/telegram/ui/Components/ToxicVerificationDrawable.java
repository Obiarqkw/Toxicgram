package org.telegram.ui.Components;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.ColorFilter;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;

/** Local Toxicgram verification badge; no dependency on Telegram's sticker servers. */
public final class ToxicVerificationDrawable extends Drawable {
    private static final long BASE=920000000000000000L;
    private static final int[] COLORS={0xffe0a52f,0xff439ef4,0xff9563df,0xff36b77a,0xffe95b61,0xff909ba9};
    private static final String[] SYMBOLS={"★","✓","◆","♛","✦","M"};
    public final long id;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path=new Path();
    private int alpha=255;
    public ToxicVerificationDrawable(long id){this.id=id;}
    public static boolean isToxic(long id){return id>=BASE && id<BASE+36;}
    @Override public void draw(Canvas canvas){
        if(!isToxic(id))return;
        Rect b=getBounds();float side=Math.min(b.width(),b.height());
        if(side<=0)return;
        float cx=b.exactCenterX(),cy=b.exactCenterY();
        int index=(int)(id-BASE);
        path.reset();
        for(int i=0;i<24;i++){
            double angle=i*Math.PI/12-Math.PI/2;
            float radius=side*(i%2==0?.48f:.41f);
            float x=cx+(float)Math.cos(angle)*radius,y=cy+(float)Math.sin(angle)*radius;
            if(i==0)path.moveTo(x,y);else path.lineTo(x,y);
        }
        path.close();
        paint.setStyle(Paint.Style.FILL);paint.setColor(COLORS[index/6]);paint.setAlpha(alpha);canvas.drawPath(path,paint);
        paint.setColor(0xffffffff);paint.setAlpha(alpha);paint.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));paint.setTextAlign(Paint.Align.CENTER);paint.setTextSize(side*.63f);
        canvas.drawText(SYMBOLS[index%6],cx,cy-(paint.ascent()+paint.descent())/2,paint);
    }
    @Override public int getIntrinsicWidth(){return org.telegram.messenger.AndroidUtilities.dp(17);}
    @Override public int getIntrinsicHeight(){return getIntrinsicWidth();}
    @Override public void setAlpha(int value){alpha=value;invalidateSelf();}
    @Override public void setColorFilter(ColorFilter filter){}
    @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
}
