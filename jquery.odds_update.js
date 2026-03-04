/**
 * オッズ更新
 *
 * options
 * @param apiUrl            api domeinを設定
 * @param raceId            race_id を設定
 * @param isPremium         1:有料会員 0:無料会員
 * @param oddsType          1 :(単勝複勝はセット) 3:枠連 4:馬連 5:ワイド 6:馬単 7:３連複 8:３連単 all:全券種
 * @param sort              odds:馬番(no) ninki:人気順
 *                              odds : view関数用意してありますが、必要に応じて　callbackApiOverrideViewで独自実装してください
 *                              ninki順の場合、view部分は用意していないので、callbackApiOverrideView　で独自実装してください
 *
 * @param autoUpdate        true:更新機能有り false:更新機能無し
 * @param cookieName        auto_odds 自動更新判定用cookei名
 * @param intervalTimer     自動更新タイマー
 * @param isBrackets        true : (*人気) false: *人気 人気に()をつけるか
 * @param isDiffValueAnim   true : オッズ比較後アニメーションclassを設定する false : 設定しない
 * @param displayDiffTime   true : 相対時間有り false : 相対時間無し
 * @param update_limit      無料会員時の更新上限(js、php共に設定が必要) Todo:パラメータを渡せるようにする
 *
 * @param compressa     true : 圧縮有り false : 圧縮無し データ量が多い券種は true推奨
 * @param debugMode     true:console.log表示 false:console.log非表示
 *
 */
(function( $ ) {

    var s = {}; //設定
    var data = {}      //最新オッズ
    var horse_list = {};//ninki順馬名
    var odds_status = ''; //取得オッズステータス
    var user_update_count = 0;//無料ユーザーの更新回数
    var connecting_flg;//連打防止

    var diff_odds = {};//更新オッズ比較用
    var diff_first_flg = true;//オッズ比較初回判定フラグ
    var mdomain = document.domain.substr( document.domain.lastIndexOf(".netkeiba") );
    var domain = mdomain; //cookie用ドメイン
    var obj_interval = null;
    //default 設定
    var defaults = {
        apiUrl        : '', //必須
        raceId        : '', //必須
        isPremium     : '', //必須
        oddsType      : 1,
        sort          : 'odds',
        autoUpdate    : true,
        intervalTimer : 30000, //30sec
        isBrackets    : true,
        isDiffValueAnim : true,
        displayDiffTime : true,
        update_limit  : 5,
        compress      : true,
        debugMode     : false,

        PremiumLinkReturnUrl : '', //有料会員登録後戻り先
        PremiumLinkReturnRf  : 'odds',//効果測定用リファラ

        //cookie
        cookieName          : 'auto_odds', //自動更新on or off

        //event selector
        oddsAutoUpdate   : 'act-auto_update'    , //自動更新イベント
        oddsManualUpdate : 'act-manual_update', //手動更新イベント

        //selector
        oddsUpdatePrefixId        : 'odds-',       //オッズ表示prefix {oddsUpdatePrefixId}-{type}_{umaban} に変換
        ninkiUpdatePrefixId       : 'ninki-',      //オッズ表示(人気順)prefix {ninkiUpdatePrefixId}-{rank|no|name}_{umaban} に変換
        oddsUpdateColorClass      : 'transition-color', //オッズ比較後のフォントカラー(アニメーション)
        oddsUpdateBackgroundclass : 'Popular',     //オッズ比較セルclass
        oddsUpdateBackgroundColor : 'UpdateOdds',  //オッズ比較後の追加セルclass(アニメーション)
        updateOfficialTimeId      : 'official_time',   //更新時間文言
        liveOddsUpdate            : 'LiveOddsUpdate',   //中間オッズ時にオッズ更新ボタン、自動更新ボタンを表示
        updateCount               : 'OddsUpLimitCount',    //更新回数

        //modal selector
        popupShowId    : 'free_odds_limit_overlay', //popup差し込み
        popupContentId : 'inline_content',       //popup 本体

        //callbacks
        callbackLoad    : false,
        callbackApiLoad : false,
        callbackApiOverrideView : false, //画面によってview部分の独自実装が必要な場合
        callbackApiComplete: false,
        callbackComplete   : false
    };

    //main
    $.oddsUpdate = function( options ) {

        var isCompress = _checkCompress();
        //設定
        s = $.extend({}, defaults, options );
        var isCompress = _checkCompress();
        if(!isCompress) {
            s.compress = false;
        }
        var setting = s;

        //load calllback
        if(s.callbackLoad) {
            s.callbackLoad(this);
        }

        if(s.debugMode) console.log('settings : ',s);

        //modal取得
        if(s.isPremium == 0) {
            _getOddsModal(s.popupShowId);
        }
        //cookieの初期化
        var ymd = _getDateYmd();
        if(getCookie(s.cookieName)) {
            var auto_odds_val = getCookie(s.cookieName);
            if(ymd != auto_odds_val) {
                document.cookie = sprintf("%s=;max-age=0",s.cookieName);
            }
        }

        //オッズ初回取得
        s.action = 'init';
        _updateOdds();

        //以下イベント
        s.action = 'update';
        
        //有料会員
        if(s.autoUpdate) {
            if(getCookie(s.cookieName) && s.isPremium == 1){
                if(s.debugMode) console.log('cookie exists');
                $('#'+s.oddsAutoUpdate).prop("checked",true);
                clearInterval(obj_interval);
                obj_interval = setInterval(function(){_updateOdds(true, true)}, s.intervalTimer);//update
            }else{
                document.cookie = sprintf("%s=;max-age=0",s.cookieName);//リセット
                $('#'+s.oddsAutoUpdate).prop("checked",false);
                if(s.debugMode) console.log('cookie emtpy');
            }
        }

        //自動更新on off
        $(document).off('click', "#"+s.oddsAutoUpdate).on('click', "#"+s.oddsAutoUpdate, function(){
            this.autoUpdateOdds = true;
            if(s.isPremium == 1) {
                if(getCookie(s.cookieName)){
                    if(s.debugMode) console.log('remove cookie');
//                    document.cookie = sprintf("%s=;max-age=0",s.cookieName);
                    document.cookie = s.cookieName + '=' + ymd + '; path=/; max-age=0; domain=' + domain + ';';

                    clearInterval( obj_interval );
                }else{
                    if(s.debugMode) console.log('set cookie');
                    //var ymd = _getDateYmd();
                    //setCookie(s.cookieName, ymd, 1);
                    var now = new Date();
                    now.setDate(now.getDate() + 1)
                    var expires = now.toGMTString();
                    clearInterval( obj_interval );
                    document.cookie = s.cookieName + '=' + ymd + '; path=/; expires=' + expires + '; domain=' + domain + ';';
                    obj_interval = setInterval(function(){_updateOdds(true, true)}, s.intervalTimer);
                }
            } else {
                //popup
                $('#'+s.oddsAutoUpdate).prop("checked",false);
                document.cookie = sprintf("%s=;max-age=0",s.cookieName);
                _popupView(1);
            }
        });

        // //更新ボタン押下
        $(document).off('click', "#"+s.oddsManualUpdate).on('click', "#"+s.oddsManualUpdate, function(){
            this.autoUpdateOdds = false;
            _updateOdds(true, false);
        });
        
        //modal 有料会員リンク
        $(document).on('click','.oddPremiumPayment',function(){
            $.colorbox.close(); //colorbox 閉じる
            var next_url = $(this).data('next_url');
            if(s.PremiumLinkReturnUrl) {
                next_url += '&return_url='+s.PremiumLinkReturnUrl;
            }
            if(s.PremiumLinkReturnRf) {
                next_url += '&rf='+s.PremiumLinkReturnRf;
            }
            location.href = next_url;
        });

        //complete calllback
        if(s.callbackComplete) {
            s.callbackComplete(this);
        }

        return(this);
    }

    /*****private****
     *
     * format_update_time のみpublic
     */

    /**
     * オッズ取得
     */
    var _updateOdds = function(updateManual, autoUpdateOdds){

        if(s.debugMode) console.log('function _updateOdds');
        if (autoUpdateOdds) {
            this.autoUpdateOdds = true;
        } else {
            this.autoUpdateOdds = false;
        }
        if(s.isDiffValueAnim) {
            var animationNode = $('.'+s.oddsUpdateBackgroundclass);
            animationNode.each(function(){
                $(this).removeClass(s.oddsUpdateBackgroundColor);
                $(this).find('[id^='+s.oddsUpdatePrefixId+']').removeClass(s.oddsUpdateColorClass);
            });
            //更新オッズ比較用
            $('[id^="'+s.oddsUpdatePrefixId+'"]').each(function(){
                var key = $(this).prop('id');
                var val = $(this).text();
                diff_odds[key] = val;
            });
        }

        if(s.action == 'update') diff_first_flg = false;
        _getOdds(s.raceId, s.oddsType, s.action, s.sort, function(resp){
            //load calllback
            if(s.callbackApiLoad) {
                s.callbackApiLoad(this, odds_status, data);
            }

            if(resp.status=='middle'){
                if(s.debugMode) console.log('show oddsUpdateButton');
                $('.'+s.liveOddsUpdate).show();
                if(s.isPremium == 0) $('.OddsUpLimitTxt02').show();
                // $(".RaceInfo_Notice").attr('class').split(/\s+/);
                $(".RaceInfo_Notice").removeClass('mt18');
                $(".RaceInfo_Notice").addClass('mt10');
            }

            if(s.debugMode) console.log('resp: %O',resp);

            data = resp.data;

            odds_status = resp.status;
            user_update_count = resp.update_count;
            var update_limit = s.update_limit - user_update_count;
            $('#'+s.updateCount).html(update_limit);

            //viewを独自に実装したい場合
            if(s.callbackApiOverrideView){
                switch(resp.status) {
                    case 'limit':
                        _popupView(2, s.update_limit );
                        break;
                    case 'NG':
                        console.log(resp.reason);
                        break;
                    default:
                        this.updateManual = updateManual;
                        s.callbackApiOverrideView(this, resp);
                }
            } else {
                switch(resp.status) {
                  case 'result':
                    _updateResultOddsView();
                    break;
                  case 'middle':
                    _updateOddsView(autoUpdateOdds);
                    break;
                  case 'yoso':
                    _updateYosoOddsView();
                    break;
                  case 'limit':
                    _popupView(2, s.update_limit );
                    break;
                  case 'NG':
                      console.log(resp.reason);
                    break;
                }
            }

            //complete calllback
            if(s.callbackApiComplete) {
                s.callbackApiComplete( this, odds_status, data );
            }
        });
    }

    /**
     * オッズ取得
     *
     * 2018.04.11 d.ito
     * axsios、ZLIBなどandroid4.0以下で対応できないのでこちらを使う
     *
     */
    var _getOdds = function(raceId, oddsType, action, sort, _callback){

        var _data = { pid : 'api_get_jra_odds' };
        _data.input   = 'UTF-8';
        _data.output  = 'jsonp';

        _data.race_id = raceId;
        _data.type = oddsType;
        _data.action = action;
        _data.sort = sort;
        _data.compress = s.compress ? 1 : 0;
        $.ajax( { type     : 'GET',
            url      : s.apiUrl,
            data     : _data,
            dataType : _data.output,
            success  : function( resp )
            {
                var data_body;
                if(_data.compress == 1){
                    if(resp.data !== ''){
                        var z_stream = ZLIB.inflateInit();
                        var oj = z_stream.inflate( base64decode(resp.data) );
                        if(oj == ''){
                            console.log('inflate error');
                            return;
                        }
                        data_body = JSON.parse(oj);
                        resp.data = data_body;
                    }
                }
                _callback(resp);
            },
            error  : function(XMLHttpRequest, textStatus, errorThrown)
            {
                console.log('XMLHttpRequest: %O',XMLHttpRequest);
                console.log('textStatus: %s',textStatus);
            }
        });
    }

    /**
     * 予想オッズ表示(odds順) 単勝のみ
     */
    var _updateYosoOddsView = function (){

        if(s.debugMode) console.log('function _updateYosoOddsView');

        // オッズ更新時間
        $('[id='+s.updateOfficialTimeId+']').text( format_update_time(data['official_datetime']) );

        var odds = data['odds'];
        $('[id^="'+s.oddsUpdatePrefixId+'"]').each(function(){
            var diff_key = $(this).prop('id');
            var tmp_data_key = $(this).attr('id').split('-');
            var data_key = tmp_data_key[1].split('_');
            var type = data_key[0];
            var odds_key = data_key[1];
            var row = odds[type][odds_key];
            var key_ninki_rank = sprintf(s.ninkiUpdatePrefixId+'%1s_%s', type, odds_key);

            if (row) {
                $(this).html(row[0]);
            
                if(s.isBrackets) {
                    $('#'+key_ninki_rank).text( '('+row[2]+')' );
                } else {
                    $('#'+key_ninki_rank).text( row[2] );
                }

                if(diff_odds[diff_key] != row[0] && s.isDiffValueAnim){
                    diff_odds[diff_key] = row[0];
                    $('[id='+diff_key+']').addClass(s.oddsUpdateColorClass);
                }
            }
        });
    }


    /**
     * 中間オッズ表示
     */
    var _updateOddsView = function (autoUpdateOdds){

        if(s.debugMode) console.log('function _updateOddsView');

        $('[id='+s.updateOfficialTimeId+']').text( format_update_time(data['official_datetime']) );

        var odds = data['odds'];
        $('[id^="'+s.oddsUpdatePrefixId+'"]').each(function(){
            var diff_key = $(this).prop('id');
            var tmp_data_key = $(this).attr('id').split('-');
            var data_key = tmp_data_key[1].split('_');
            var type = data_key[0];
            var odds_key = data_key[1];
            var row = odds[type][odds_key];
            var key_ninki_rank = sprintf(s.ninkiUpdatePrefixId+'%1s_%s', type, odds_key);

            if (row) {
                $(this).html(row[0]);
            
                if(s.isBrackets) {
                    $('#'+key_ninki_rank).text( '('+row[2]+')' );
                } else {
                    $('#'+key_ninki_rank).text( row[2] );
                }

                if(s.isDiffValueAnim) {
                    if(!diff_first_flg && !autoUpdateOdds){ //初回以外
                        $(this).parents('.'+s.oddsUpdateBackgroundclass).addClass(s.oddsUpdateBackgroundColor);
                    }
                    if(diff_odds[diff_key] != row[0]){
                        diff_odds[diff_key] = row[0];
                        $('[id='+diff_key+']').addClass(s.oddsUpdateColorClass);
                    }
                }
            }
        });
    }

    /**
     * 確定オッズ表示
     */
    var _updateResultOddsView = function (){

        if(s.debugMode) console.log('function _updateResultOddsView');

        var odds = data['odds'];
        $('[id^="'+s.oddsUpdatePrefixId+'"]').each(function(){
            var diff_key = $(this).prop('id');
            var tmp_data_key = $(this).attr('id').split('-');
            var data_key = tmp_data_key[1].split('_');
            var type = data_key[0];
            var odds_key = data_key[1];
            var row = odds[type][odds_key];
            var key_ninki_rank = sprintf(s.ninkiUpdatePrefixId+'%1s_%s', type, odds_key);

            if (row) {
                $(this).html(row[0]);
            
                if(s.isBrackets) {
                    $('#'+key_ninki_rank).text( '('+row[2]+')' );
                } else {
                    $('#'+key_ninki_rank).text( row[2] );
                }

                if(diff_odds[diff_key] != row[0] && s.isDiffValueAnim){
                    diff_odds[diff_key] = row[0];
                    $('[id='+diff_key+']').addClass(s.oddsUpdateColorClass);
                }
            }
        });
    }
    /**
     * @param pattern 1:有料会員案内 2:手動更新ボタン
     * @param update_count 2:手動更新ボタンの更新回数
     */
    var _popupView = function ( pattern, update_count ) {
        if(s.debugMode) console.log('function _popupView');

        $('#premiumm_info').hide();
        $('#free_update_limit').hide();

        if(pattern == '1') {
            $('#premiumm_info').show();//上限
        } else if(pattern == '2') {

            var update_limit = s.update_limit - update_count;
            $('#odds_update_rest').html(update_limit);

            if(s.update_limit <= update_count) {
                $('#free_update_limit').show();//上限
            }
        }
        $.colorbox( {
            onOpen:function(){
                $("#cboxWrapper").addClass("OddsInfoModal");
            },
            inline: true,
            width: '98%',
            height: '770px',
            maxWidth: '700px',
            transition: "fade",
            reposition: false,
            onComplete: function() {
                $('#OddsInfoSlideBox').slick('refresh');
                setTimeout(function(){
                    $.colorbox.position(0);
                },500);
            },
            href:$('#inline_content'),
        });
    }
    /**
     * 更新時間のフォーマットを変換
     *
     * @param new 2018-01-20 15:59:40
     *
     * return 15:59 or 15:59(8分前)  (*分前)は現在時刻からの相対時間
     */
    format_update_time = function(new_time) {

if(!new_time){
    new_time = _getDateYmd();
}



        if(s.isPremium == '1' || !s.displayDiffTime) {
            new_time = new_time.replace( /-/g , "/" ) ;
            var date_new = new Date(new_time);
            var h = date_new.getHours();
            var m = date_new.getMinutes();
            var time = sprintf('%s:%02s',h, m);
        } else {
            new_time = new_time.replace( /-/g , "/" ) ;
            var date_new = new Date();
            var date_old = new Date(new_time);
            var new_u_time = Math.floor( date_new.getTime() / 1000 );
            var old_u_time = Math.floor( date_old.getTime() / 1000 );
            var diff_time_min = Math.floor((new_u_time - old_u_time) / 60);
            var h = date_old.getHours();
            var m = date_old.getMinutes();
            var time = sprintf('%s:%02s(%s分前)',h, m, diff_time_min);
        }
        return time;
    }

    /**
     *　無料会員案内用modalを取得する
     *
     */
    var _getOddsModal = function ( _show_id ) {

        if(s.debugMode) console.log('function _getOddsModal : show_id',_show_id);

        var _data = { pid : 'api_get_odds_modal' };
        _data.input   = 'UTF-8';
        _data.output  = 'jsonp';
        $.ajax( { type     : 'GET',
            url      : '/api/api_get_odds_modal.html',
            data     : _data,
            dataType : _data.output,
            success  : function( data )
            {

                $( '#' + _show_id ).html( data );
            }
        });
    }

    /**
     *  現在日時を返す
     */
    var _getDateYmd = function () {
        var now   = new Date();
        var year  = now.getFullYear(); //年
        var month = now.getMonth();    //月
        var day   = now.getDate();     //日
        return sprintf('%04s%02s%02s', year, month, day);
    }

    /**
     * android 4.0.以下対応 lib ZLIBが動かないので下記条件をチェックする
     *
     * ブラウザ 且つ android4.0以下の場合はfalse
     */
    var _checkCompress = function() {
       var cookie_name = 'browser_appli[keiba]';
       var appli = getCookie(cookie_name);
       var isCompress = true;
       if(appli) {
           return isCompress;
       }
       var ua = navigator.userAgent.toLowerCase();
       if(ua.indexOf('android') > 0) {
           if(ua.match(/android ([\.\d]+)/)){
               var os_v = RegExp.$1;
               var os_s = os_v.split('.');
               //テスト
               //os_s[0] = '4';
               //os_s[1] = '0';
               //os_s[2] = '4';マイナーマイナーまで判定したい場合はこれを使う
               //マイナーバージョンまでをFloatへ変換
               var v_major_minor = parseFloat(os_s[0]+'.'+os_s[1]);
               if(4 < v_major_minor) { //4.0より上
                   isCompress = true;
               } else { //4.0以下
                   isCompress = false;
               }
           }
       }
       return isCompress;
    }
})( jQuery );
