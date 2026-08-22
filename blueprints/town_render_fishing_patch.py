"""Force fishing life actions to leave the office through the central door first."""


def patch_render_fishing(html: str) -> str:
    html = html.replace(
        "    if(mode==='fishing'){\n"
        "      const spot=pick(FISH_SPOTS);\n"
        "      a.plantTarget=null;\n"
        "      a.idle='fishing';a.idleAction='walk';\n"
        "      a.targetX=spot.x;a.targetY=spot.y;\n"
        "      a.state='idleWalk';a.walkPhase=0;\n"
        "      return;\n"
        "    }",
        "    if(mode==='fishing'){\n"
        "      const spot=pick(FISH_SPOTS);\n"
        "      a.plantTarget=null;\n"
        "      a.idle='fishing';a.idleAction='walk';\n"
        "      a.fishingSpot=spot;a.fishingStage='exit';\n"
        "      a.targetX=officeExit.x;a.targetY=officeExit.y;\n"
        "      a.state='idleWalk';a.walkPhase=0;\n"
        "      return;\n"
        "    }",
    )
    html = html.replace(
        "        if(moveToward(a,a.targetX,a.targetY,34*dt)){\n"
        "          if(a.idle==='sweep'&&Array.isArray(a.sweepRoute)&&a.sweepRoute.length){",
        "        if(moveToward(a,a.targetX,a.targetY,34*dt)){\n"
        "          if(a.idle==='fishing'&&a.fishingStage==='exit'&&a.fishingSpot){a.path=[];a.pathTarget='';a.fishingStage='spot';a.targetX=a.fishingSpot.x;a.targetY=a.fishingSpot.y;a.state='idleWalk';a.idleAction='walk';return;}\n"
        "          if(a.idle==='sweep'&&Array.isArray(a.sweepRoute)&&a.sweepRoute.length){",
    )
    html = html.replace(
        "          a.state='idle';a.idleAction=a.idle;a.timer=rand(1.0,3.8);",
        "          a.state='idle';a.idleAction=a.idle;a.timer=rand(1.0,3.8);if(a.idle==='fishing')a.fishingStage='fishing';",
    )
    return html
