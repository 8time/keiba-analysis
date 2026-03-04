$(function() {
	// $("#btn_odds_summary").click(function(){
	// 	$("#odds_summary").hide();
	// 	$("#odds_tan_block").hide();
	// 	$("#odds_fuku_block").hide();
	// 	$("#odds_summary").show();
	// });
	// $("#btn_odds_tan_block").click(function(){
	// 	$("#odds_summary").hide();
	// 	$("#odds_tan_block").hide();
	// 	$("#odds_fuku_block").hide();
	// 	$("#odds_tan_block").show();
	// });
	// $("#btn_odds_fuku_block").click(function(){
	// 	$("#odds_summary").hide();
	// 	$("#odds_tan_block").hide();
	// 	$("#odds_fuku_block").hide();
	// 	$("#odds_fuku_block").show();
	// });

	//=================================================
	//買い目リストのチェック時に実行
	//=================================================
	$(document).on("click","[id^='chk_b']" , function(){
		update_cart_checkbox_tanfuku(_cart_group_bet, this.value, 1, '', this.checked);
		view_check_count_tanfuku();
	});

});

//===========================================================
// Docment Readyになったときに処理するもの
//===========================================================
$(document).ready(function ()
{
	//==============================================================
	// Document Readyになったときに処理する
	//==============================================================
	// $("#odds_summary").hide();
	// $("#odds_tan_block").hide();
	// $("#odds_fuku_block").hide();
	// $("#odds_tan_block").show();
	// $("#btn_odds_tan_block").addClass('Active');

	//MY印の初期値
	if (typeof _cart_group_house != "undefined" ) {
		cart_get_itemlist( _cart_group_house, init_select_mark_tanfuku );

		//オッズ表示時の買い目チェック
		cart_get_itemlist( _cart_group_bet, init_select_kaime_tanfuku );
	}
	

	//ボタンをアクティブ表示
	$('[id*="btn_odds_"]').click(function() {
		$('.RaceOdds_Menu02 a').removeClass('Active');
		$(this).addClass('Active');
	})
});

//===========================================================
// MY印の初期値をセットする
// in: _cart  ...cart_get_itemlist()の戻り(item_id)
//===========================================================
function init_select_mark_tanfuku( _cart )
{
    console.log('init_select_mark_tanfuku');

    var ary_mark = new Array();

	// 該当レースで選択されたMY印を取得
    for(var item_id in _cart)
	{
		var tmp = _cart[item_id]['_cd'];
		if (tmp) {
			var mark = tmp.split('_');
			if ('1' in mark)
			{
				ary_mark[ item_id ] = mark[1];	//重み印モードのとき
			}
			else
			{
				ary_mark[ item_id ] = 100;		//チェックモードのとき
			}
			console.log('item_id='+item_id+' client_data='+ary_mark[ item_id ]);
		}
		
    }

	// ユーザーのMY印をセット
    $("[id^='mymark']").each(function()
	{ // ドキュメント内のMY印の選択ボックスの数だけループ

		var box 		= $(this);
		var tmp_seq 	= box[0].id;			//seq
		if (tmp_seq) {
			var seq 	= tmp_seq.split('_');
			var mark_data 	= ary_mark[seq[1]];
			if (!mark_data || mark_data == 0) {
				mark_data = '00';
			}

			$(this).parent().removeClass('MarkIcon Mark00');
			$(this).parent().addClass('MarkIcon Mark'+mark_data);
			$(this).attr('value', mark_data);
		}
    });
}

//===========================================================
// オッズ検索結果にて、
// すでにチェック済みの買い目にチェックを入れる
// in: _cart       = cart_get_itemlist()の戻り(item_id)
//     _aryID['0'] = チェック対象のchkboxのidタグ検索キー
//===========================================================
function init_select_kaime_tanfuku( _cart )
{
    console.log('init_select_kaime_tanfuku');


    $("[id^='chk_']").each(function()
	{
		var chkbox 	= $(this);
		var count 	= chkbox.val();
	    for(var item_id in _cart)
		{

			if (item_id == count)
			{// すでにチェック済みの買い目と一致したとき

				chkbox.prop("checked", true);	// 該当chkboxをチェック
			}
	    }
    });
	view_check_count_tanfuku();		// チェック数をカウント(初期表示)
}

//------------------------------------------------------------
// 買い目点数のカウント・表示
//------------------------------------------------------------
function view_check_count_tanfuku()
{
    var cnt = 0;
    $("[id^='chk_b']").each(function()
	{
		var chkbox = $(this);
		if ( chkbox.prop("checked") == true )
		{
			cnt++;
		}
    });
    console.log('view_check_count _cnt='+cnt);
    $('#odds_select').text( cnt);
}

//------------------------------------------------------------
// カートを更新する(checkbox)
//------------------------------------------------------------
function update_cart_checkbox_tanfuku( _group, _item_id, _item_value, _client_data, _checked )
{
    console.log('update_cart_checkbox');

    if(true == _checked){
	cart_add_item( _group, _item_id, _item_value, '', _client_data );
    }else{
	cart_remove_item( _group, _item_id );
    }
}
